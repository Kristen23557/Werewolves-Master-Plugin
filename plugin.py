import os
import json
import time
import random
import asyncio
import datetime
import hashlib
from typing import List, Tuple, Type, Dict, Any, Optional, Set
from enum import Enum
from src.plugin_system import (
    BasePlugin,
    register_plugin,
    BaseCommand,
    ComponentInfo,
    ConfigField
)
from src.plugin_system.apis import send_api, chat_api
from src.plugin_system.apis import person_api

# ==================== 枚举定义 ====================
class GamePhase(Enum):
    SETUP = "setup"
    NIGHT = "night"
    DAY = "day"
    VOTE = "vote"
    HUNTER_REVENGE = "hunter_revenge"
    WITCH_SAVE_PHASE = "witch_save_phase"
    ENDED = "ended"

class PlayerStatus(Enum):
    ALIVE = "alive"
    DEAD = "dead"
    EXILED = "exiled"

class DeathReason(Enum):
    WOLF_KILL = "wolf_kill"
    VOTE = "vote"
    POISON = "poison"
    HUNTER_SHOOT = "hunter_shoot"
    SUICIDE = "suicide"
    WHITE_WOLF = "white_wolf"
    LOVER_SUICIDE = "lover_suicide"

class Camp(Enum):
    VILLAGE = "village"
    WOLF = "wolf"
    THIRD_PARTY = "third_party"
    LOVER = "lover"

class WitchStatus(Enum):
    HAS_BOTH = "has_both"
    HAS_SAVE_ONLY = "has_save_only"
    HAS_POISON_ONLY = "has_poison_only"
    USED_BOTH = "used_both"

# ==================== 角色定义 ====================
ROLES = {
    # 基础角色
    "villager": {
        "name": "村民",
        "camp": Camp.VILLAGE,
        "is_sub": False,
        "night_action": False,
        "day_action": False,
        "command": None,
        "description": "普通村民，没有特殊能力，通过推理找出狼人"
    },
    "seer": {
        "name": "预言家",
        "camp": Camp.VILLAGE,
        "is_sub": False,
        "night_action": True,
        "day_action": False,
        "command": "check",
        "description": "每晚可以查验一名玩家的阵营"
    },
    "witch": {
        "name": "女巫",
        "camp": Camp.VILLAGE,
        "is_sub": False,
        "night_action": True,
        "day_action": False,
        "command": "save/poison",
        "description": "有一瓶解药和一瓶毒药，每晚可以使用其中一瓶"
    },
    "hunter": {
        "name": "猎人",
        "camp": Camp.VILLAGE,
        "is_sub": False,
        "night_action": False,
        "day_action": True,
        "command": "shoot",
        "description": "死亡时可以开枪带走一名玩家（被毒杀除外）"
    },
    "wolf": {
        "name": "狼人",
        "camp": Camp.WOLF,
        "is_sub": False,
        "night_action": True,
        "day_action": False,
        "command": "kill",
        "description": "每晚可以共同决定击杀一名玩家"
    },
    # 高级角色
    "hidden_wolf": {
        "name": "隐狼",
        "camp": Camp.WOLF,
        "is_sub": False,
        "night_action": False,
        "day_action": False,
        "command": None,
        "description": "查验为好人，不能自爆，不能参与狼人夜间的杀人。当其他所有狼人队友出局后，隐狼获得刀人能力"
    },
    "guard": {
        "name": "守卫",
        "camp": Camp.VILLAGE,
        "is_sub": False,
        "night_action": True,
        "day_action": False,
        "command": "guard",
        "description": "每晚可以守护一名玩家（包括自己），使其免于狼人的袭击。不能连续两晚守护同一名玩家"
    },
    "magician": {
        "name": "魔术师",
        "camp": Camp.VILLAGE,
        "is_sub": False,
        "night_action": True,
        "day_action": False,
        "command": "swap",
        "description": "每晚可以选择交换两名玩家的号码牌，持续到下一个夜晚"
    },
    "double_faced": {
        "name": "双面人",
        "camp": Camp.THIRD_PARTY,
        "is_sub": False,
        "night_action": False,
        "day_action": False,
        "command": None,
        "description": "游戏开始时无固定阵营。被狼杀加入狼队，被投票加入好人，毒药无效"
    },
    "spiritualist": {
        "name": "通灵师",
        "camp": Camp.VILLAGE,
        "is_sub": False,
        "night_action": True,
        "day_action": False,
        "command": "inspect",
        "description": "每晚可以查验一名玩家的具体身份。不能被守卫守护，且女巫的解药对其无效"
    },
    "successor": {
        "name": "继承者",
        "camp": Camp.VILLAGE,
        "is_sub": False,
        "night_action": False,
        "day_action": False,
        "command": None,
        "description": "当相邻的玩家（号码相邻）有神民出局时，继承者会秘密获得该神民的技能"
    },
    "painter": {
        "name": "画皮",
        "camp": Camp.WOLF,
        "is_sub": False,
        "night_action": True,
        "day_action": False,
        "command": "disguise",
        "description": "游戏第二夜起，可以潜入一名已出局玩家的身份"
    },
    "white_wolf": {
        "name": "白狼王",
        "camp": Camp.WOLF,
        "is_sub": False,
        "night_action": False,
        "day_action": True,
        "command": "explode",
        "description": "白天投票放逐阶段，可以随时翻牌自爆，并带走一名玩家"
    },
    "cupid": {
        "name": "丘比特",
        "camp": Camp.THIRD_PARTY,
        "is_sub": False,
        "night_action": True,
        "day_action": False,
        "command": "choose",
        "description": "游戏第一晚，选择两名玩家成为情侣"
    }
}

# ==================== 消息发送工具类 ====================
class MessageSender:
    """消息发送工具类，封装正确的API调用方式"""
    
    @staticmethod
    async def send_private_message(user_id: str, message: str) -> bool:
        """发送私聊消息"""
        try:
            # 获取用户的私聊流
            stream = chat_api.get_stream_by_user_id(user_id, "qq")
            if not stream:
                print(f"❌ 未找到用户 {user_id} 的私聊流")
                return False
            
            # 使用正确的API发送消息
            success = await send_api.text_to_stream(
                text=message,
                stream_id=stream.stream_id,
                storage_message=True
            )
            
            if success:
                print(f"✅ 私聊消息发送成功: {user_id}")
            else:
                print(f"❌ 私聊消息发送失败: {user_id}")
            
            return success
            
        except Exception as e:
            print(f"❌ 发送私聊消息异常: {e}")
            return False
    
    @staticmethod
    async def send_group_message(group_id: str, message: str) -> bool:
        """发送群聊消息"""
        try:
            # 获取群聊流
            stream = chat_api.get_stream_by_group_id(group_id, "qq")
            if not stream:
                print(f"❌ 未找到群组 {group_id} 的聊天流")
                return False
            
            # 使用正确的API发送消息
            success = await send_api.text_to_stream(
                text=message,
                stream_id=stream.stream_id,
                storage_message=True
            )
            
            if success:
                print(f"✅ 群聊消息发送成功: {group_id}")
            else:
                print(f"❌ 群聊消息发送失败: {group_id}")
            
            return success
            
        except Exception as e:
            print(f"❌ 发送群聊消息异常: {e}")
            return False

# ==================== 游戏管理器 ====================
class WerewolfGameManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.games = {}
            cls._instance.player_profiles = {}
            cls._instance.last_activity = {}
            cls._instance._load_profiles()
        return cls._instance
    
    def _load_profiles(self):
        """加载玩家档案"""
        profiles_dir = os.path.join(os.path.dirname(__file__), "users")
        os.makedirs(profiles_dir, exist_ok=True)
        
        for filename in os.listdir(profiles_dir):
            if filename.endswith('.json'):
                file_path = os.path.join(profiles_dir, filename)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        profile = json.load(f)
                        qq = filename[:-5]  # 去掉.json后缀
                        self.player_profiles[qq] = profile
                except Exception as e:
                    print(f"加载玩家档案 {filename} 失败: {e}")
    
    def _save_profile(self, qq: str):
        """保存玩家档案"""
        if qq not in self.player_profiles:
            return
        
        profiles_dir = os.path.join(os.path.dirname(__file__), "users")
        os.makedirs(profiles_dir, exist_ok=True)
        
        file_path = os.path.join(profiles_dir, f"{qq}.json")
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.player_profiles[qq], f, ensure_ascii=False, indent=2)
    
    def get_or_create_profile(self, qq: str, name: str) -> Dict[str, Any]:
        """获取或创建玩家档案"""
        if qq not in self.player_profiles:
            self.player_profiles[qq] = {
                "qq": qq,
                "name": name,  # 使用传入的名称
                "total_games": 0,
                "wins": 0,
                "losses": 0,
                "kills": 0,
                "votes": 0,
                "recent_win_rate": 0,
                "recent_games": [],
                "created_time": datetime.datetime.now().isoformat()
            }
            self._save_profile(qq)
        return self.player_profiles[qq]
    
    def create_game(self, room_id: str, host_qq: str, group_id: str, host_name: str) -> Dict[str, Any]:
        """创建新游戏并自动加入房主"""
        game = {
            "room_id": room_id,
            "host": host_qq,
            "group_id": group_id,
            "players": {},
            "player_order": [],
            "settings": {
                "player_count": 8,
                "roles": {
                    "villager": 2,
                    "seer": 1,
                    "witch": 1,
                    "hunter": 1,
                    "wolf": 2,
                    "hidden_wolf": 0,
                    "guard": 0,
                    "magician": 0,
                    "double_faced": 0,
                    "spiritualist": 0,
                    "successor": 0,
                    "painter": 0,
                    "white_wolf": 0,
                    "cupid": 0
                }
            },
            "phase": GamePhase.SETUP.value,
            "day_count": 0,
            "night_actions": {},
            "day_actions": {},
            "votes": {},
            "death_queue": [],
            "lovers": [],
            "guard_protected": None,
            "last_guard_target": None,
            "magician_swap": None,
            "painter_disguised": None,
            "successor_skills": {},
            "hidden_wolf_awakened": False,
            "white_wolf_exploded": False,
            "witch_status": WitchStatus.HAS_BOTH.value,
            "witch_save_candidates": [],
            "witch_used_save_this_night": False,
            "witch_used_poison_this_night": False,
            "created_time": datetime.datetime.now().isoformat(),
            "started_time": None,
            "ended_time": None,
            "winner": None,
            "game_code": None,
            "phase_start_time": time.time(),
            "saved_players": set()  # 新增：被女巫解药拯救的玩家
        }
        
        # 自动加入房主
        self.get_or_create_profile(host_qq, host_name)
        game["players"][host_qq] = {
            "name": host_name,
            "qq": host_qq,
            "number": 1,
            "role": None,
            "original_role": None,
            "status": PlayerStatus.ALIVE.value,
            "death_reason": None,
            "killer": None,
            "has_acted": False,
            "is_lover": False,
            "lover_partner": None,
            "inherited_skill": None
        }
        game["player_order"].append(host_qq)
        
        self.games[room_id] = game
        self.last_activity[room_id] = time.time()
        self._save_game_file(room_id)
        return game
    
    def join_game(self, room_id: str, player_qq: str, player_name: str) -> bool:
        """玩家加入游戏"""
        if room_id not in self.games:
            return False
        
        game = self.games[room_id]
        if len(game["players"]) >= game["settings"]["player_count"]:
            return False
        
        if player_qq in game["players"]:
            return False
        
        # 创建或获取玩家档案
        self.get_or_create_profile(player_qq, player_name)
        
        game["players"][player_qq] = {
            "name": player_name,
            "qq": player_qq,
            "number": len(game["players"]) + 1,
            "role": None,
            "original_role": None,
            "status": PlayerStatus.ALIVE.value,
            "death_reason": None,
            "killer": None,
            "has_acted": False,
            "is_lover": False,
            "lover_partner": None,
            "inherited_skill": None
        }
        game["player_order"].append(player_qq)
        
        self.last_activity[room_id] = time.time()
        self._save_game_file(room_id)
        return True
    
    def destroy_game(self, room_id: str) -> bool:
        """销毁房间"""
        if room_id not in self.games:
            return False
        
        # 删除游戏文件
        games_dir = os.path.join(os.path.dirname(__file__), "games")
        file_path = os.path.join(games_dir, f"{room_id}.json")
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"删除游戏文件失败: {e}")
        
        # 从内存中移除
        del self.games[room_id]
        if room_id in self.last_activity:
            del self.last_activity[room_id]
        
        return True
    
    def start_game(self, room_id: str) -> bool:
        """开始游戏"""
        if room_id not in self.games:
            return False
        
        game = self.games[room_id]
        if len(game["players"]) < 6:
            return False
        
        # 分配角色
        roles_to_assign = []
        for role_id, count in game["settings"]["roles"].items():
            roles_to_assign.extend([role_id] * count)
        
        if len(roles_to_assign) != len(game["players"]):
            return False
        
        random.shuffle(roles_to_assign)
        
        for i, player_qq in enumerate(game["player_order"]):
            game["players"][player_qq]["role"] = roles_to_assign[i]
            game["players"][player_qq]["original_role"] = roles_to_assign[i]
        
        game["phase"] = GamePhase.NIGHT.value
        game["day_count"] = 1  # 第一夜
        game["started_time"] = datetime.datetime.now().isoformat()
        game["phase_start_time"] = time.time()
        self.last_activity[room_id] = time.time()
        self._save_game_file(room_id)
        return True
    
    def _save_game_file(self, room_id: str):
        """保存游戏文件"""
        if room_id not in self.games:
            return
        
        game = self.games[room_id]
        games_dir = os.path.join(os.path.dirname(__file__), "games")
        os.makedirs(games_dir, exist_ok=True)
        
        file_path = os.path.join(games_dir, f"{room_id}.json")
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(game, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存游戏文件失败: {e}")
    
    def archive_game(self, room_id: str):
        """归档游戏"""
        if room_id not in self.games:
            return None
        
        game = self.games[room_id]
        
        # 生成对局码
        game_code = hashlib.md5(f"{room_id}{time.time()}".encode()).hexdigest()[:12]
        game["game_code"] = game_code
        
        # 更新玩家档案
        for player_qq, player in game["players"].items():
            if player_qq in self.player_profiles:
                profile = self.player_profiles[player_qq]
                profile["total_games"] += 1
                
                # 判断胜负
                player_camp = ROLES[player["original_role"]]["camp"]
                if player["is_lover"]:
                    player_camp = Camp.LOVER
                
                is_winner = False
                if game["winner"] == "village" and player_camp == Camp.VILLAGE:
                    is_winner = True
                elif game["winner"] == "wolf" and player_camp == Camp.WOLF:
                    is_winner = True
                elif game["winner"] == "lover" and player_camp == Camp.LOVER:
                    is_winner = True
                elif game["winner"] == "third_party" and player_camp == Camp.THIRD_PARTY:
                    is_winner = True
                
                if is_winner:
                    profile["wins"] += 1
                else:
                    profile["losses"] += 1
                
                # 统计击杀和票杀
                if player["killer"] == player_qq:  # 自杀不算
                    pass
                elif player["death_reason"] in [DeathReason.HUNTER_SHOOT.value, DeathReason.POISON.value]:
                    killer_profile = self.player_profiles.get(player["killer"])
                    if killer_profile:
                        killer_profile["kills"] += 1
                elif player["death_reason"] == DeathReason.VOTE.value:
                    # 票杀统计给所有投票的玩家
                    for voter_qq in game.get("votes", {}).keys():
                        if game["votes"][voter_qq] == player["number"]:
                            voter_profile = self.player_profiles.get(voter_qq)
                            if voter_profile:
                                voter_profile["votes"] += 1
                
                # 更新最近游戏记录
                profile["recent_games"].append({
                    "game_code": game_code,
                    "role": player["original_role"],
                    "won": is_winner,
                    "timestamp": game["ended_time"]
                })
                if len(profile["recent_games"]) > 10:
                    profile["recent_games"] = profile["recent_games"][-10:]
                
                # 计算最近胜率
                recent_wins = sum(1 for g in profile["recent_games"] if g["won"])
                profile["recent_win_rate"] = recent_wins / len(profile["recent_games"]) if profile["recent_games"] else 0
                
                self._save_profile(player_qq)
        
        # 移动文件到finished文件夹
        games_dir = os.path.join(os.path.dirname(__file__), "games")
        finished_dir = os.path.join(games_dir, "finished")
        os.makedirs(finished_dir, exist_ok=True)
        
        source_file = os.path.join(games_dir, f"{room_id}.json")
        target_file = os.path.join(finished_dir, f"{game_code}.json")
        
        try:
            if os.path.exists(source_file):
                os.rename(source_file, target_file)
        except Exception as e:
            print(f"移动游戏文件失败: {e}")
        
        # 从内存中移除
        del self.games[room_id]
        if room_id in self.last_activity:
            del self.last_activity[room_id]
        
        return game_code
    
    def get_archived_game(self, game_code: str) -> Optional[Dict[str, Any]]:
        """获取已归档的游戏"""
        finished_dir = os.path.join(os.path.dirname(__file__), "games", "finished")
        file_path = os.path.join(finished_dir, f"{game_code}.json")
        
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"读取归档游戏 {game_code} 失败: {e}")
        return None
    
    def cleanup_inactive_games(self):
        """清理不活跃的游戏"""
        current_time = time.time()
        rooms_to_remove = []
        
        for room_id, last_active in self.last_activity.items():
            if room_id not in self.games:
                continue
                
            game = self.games[room_id]
            timeout = 1800 if game["phase"] != GamePhase.SETUP.value else 1200
            
            if current_time - last_active > timeout:
                rooms_to_remove.append(room_id)
        
        for room_id in rooms_to_remove:
            # 归档游戏而不是直接删除
            if room_id in self.games:
                game = self.games[room_id]
                game["winner"] = "inactive"
                game["ended_time"] = datetime.datetime.now().isoformat()
                self.archive_game(room_id)

# ==================== 游戏逻辑处理器 ====================
class GameLogicProcessor:
    def __init__(self, game_manager: WerewolfGameManager):
        self.game_manager = game_manager
    
    async def process_night_actions(self, room_id: str) -> bool:
        """处理夜晚行动"""
        if room_id not in self.game_manager.games:
            return False
        
        game = self.game_manager.games[room_id]
        
        # 检查是否所有玩家都已完成行动（除了女巫的解药阶段）
        all_acted = await self._check_all_night_actions_completed(game, room_id)
        
        if not all_acted:
            return False
        
        # 如果女巫有解药且未使用，进入女巫解药阶段
        witch_player = self._get_player_by_role(game, "witch")
        if (witch_player and 
            witch_player["status"] == PlayerStatus.ALIVE.value and
            game["witch_status"] in [WitchStatus.HAS_BOTH.value, WitchStatus.HAS_SAVE_ONLY.value] and
            not game["witch_used_save_this_night"]):
            
            # 计算可能死亡的玩家
            potential_deaths = await self._calculate_potential_deaths(game, room_id)
            game["witch_save_candidates"] = potential_deaths
            
            if potential_deaths:
                game["phase"] = GamePhase.WITCH_SAVE_PHASE.value
                game["phase_start_time"] = time.time()
                self.game_manager.last_activity[room_id] = time.time()
                self.game_manager._save_game_file(room_id)
                
                # 通知女巫
                candidates_text = "\n".join([f"{num}号 - {name}" for num, name in potential_deaths])
                await self._send_private_message(game, witch_player["qq"],
                                               f"💊 解药就绪阶段！以下玩家可能会在今晚死亡：\n{candidates_text}\n\n"
                                               f"请选择使用解药拯救其中一名玩家，或输入 /wwg skip 跳过使用解药\n"
                                               f"⏰ 请在 {self._get_phase_timeout('witch_save')} 内完成选择")
                return True
        
        # 如果没有女巫解药阶段，直接处理所有行动
        return await self._process_all_night_actions(game, room_id)
    
    async def process_witch_save_phase(self, room_id: str) -> bool:
        """处理女巫解药阶段"""
        if room_id not in self.game_manager.games:
            return False
        
        game = self.game_manager.games[room_id]
        
        # 处理女巫解药行动
        witch_save_action = game["night_actions"].get("witch_save")
        witch_skip = game["night_actions"].get("witch_skip")
        
        witch_player = self._get_player_by_role(game, "witch")
        if not witch_player:
            return await self._process_all_night_actions(game, room_id)
        
        if witch_save_action:
            try:
                target_num = int(witch_save_action)
                # 检查目标是否在候选列表中
                candidate_numbers = [num for num, _ in game["witch_save_candidates"]]
                if target_num in candidate_numbers:
                    # 使用解药
                    game["witch_used_save_this_night"] = True
                    
                    # 更新女巫状态
                    if game["witch_status"] == WitchStatus.HAS_BOTH.value:
                        game["witch_status"] = WitchStatus.HAS_POISON_ONLY.value
                    elif game["witch_status"] == WitchStatus.HAS_SAVE_ONLY.value:
                        game["witch_status"] = WitchStatus.USED_BOTH.value
                    
                    # 标记被拯救的玩家
                    target_player = self._get_player_by_number(game, target_num)
                    if target_player:
                        game["saved_players"].add(target_player["qq"])
                    
                    await self._send_private_message(game, witch_player["qq"],
                                                   f"💊 你使用解药拯救了玩家 {target_num} 号")
            
            except ValueError:
                pass
        
        elif witch_skip:
            # 女巫选择跳过使用解药
            game["witch_used_save_this_night"] = True  # 标记为已处理
            await self._send_private_message(game, witch_player["qq"],
                                           "💊 你选择保留解药")
        
        # 继续处理所有夜晚行动
        return await self._process_all_night_actions(game, room_id)
    
    async def _check_all_night_actions_completed(self, game: Dict[str, Any], room_id: str) -> bool:
        """检查是否所有玩家都已完成夜晚行动"""
        # 获取所有需要夜晚行动的玩家
        night_action_players = []
        for player in game["players"].values():
            if (player["status"] == PlayerStatus.ALIVE.value and
                ROLES[player["role"]]["night_action"] and
                player["role"] != "witch"):  # 女巫特殊处理
                night_action_players.append(player)
        
        # 检查这些玩家是否都已完成行动
        for player in night_action_players:
            role_action_key = self._get_role_action_key(player["role"])
            if role_action_key not in game["night_actions"]:
                return False
        
        return True
    
    async def _calculate_potential_deaths(self, game: Dict[str, Any], room_id: str) -> List[Tuple[int, str]]:
        """计算可能死亡的玩家"""
        potential_deaths = []
        
        # 模拟计算狼人击杀
        wolf_kill_action = game["night_actions"].get("wolf_kill")
        if wolf_kill_action:
            try:
                target_num = int(wolf_kill_action)
                target_player = self._get_player_by_number(game, target_num)
                if (target_player and 
                    target_player["status"] == PlayerStatus.ALIVE.value and
                    target_player["role"] != "double_faced"):  # 双面人不死亡，只转换阵营
                    potential_deaths.append((target_num, target_player["name"]))
            except ValueError:
                pass
        
        return potential_deaths
    
    async def _process_all_night_actions(self, game: Dict[str, Any], room_id: str) -> bool:
        """处理所有夜晚行动"""
        # 按角色优先级处理行动
        actions_processed = {
            "cupid": False,
            "guard": False,
            "wolf": False,
            "seer": False,
            "witch_poison": False,
            "spiritualist": False,
            "magician": False,
            "painter": False
        }
        
        # 丘比特行动（仅第一夜）
        if game["day_count"] == 1:
            await self._process_cupid_action(game, room_id)
            actions_processed["cupid"] = True
        
        # 守卫行动
        await self._process_guard_action(game, room_id)
        actions_processed["guard"] = True
        
        # 狼人行动
        await self._process_wolf_action(game, room_id)
        actions_processed["wolf"] = True
        
        # 预言家行动
        await self._process_seer_action(game, room_id)
        actions_processed["seer"] = True
        
        # 女巫毒药行动
        await self._process_witch_poison_action(game, room_id)
        actions_processed["witch_poison"] = True
        
        # 通灵师行动
        await self._process_spiritualist_action(game, room_id)
        actions_processed["spiritualist"] = True
        
        # 魔术师行动
        await self._process_magician_action(game, room_id)
        actions_processed["magician"] = True
        
        # 画皮行动（第二夜及以后）
        if game["day_count"] >= 2:
            await self._process_painter_action(game, room_id)
            actions_processed["painter"] = True
        
        # 执行死亡
        await self._execute_deaths(game, room_id)
        
        # 检查游戏是否结束
        if await self._check_game_end(game, room_id):
            return True
        
        # 进入白天
        game["phase"] = GamePhase.DAY.value
        game["phase_start_time"] = time.time()
        game["night_actions"] = {}
        game["witch_save_candidates"] = []
        game["witch_used_save_this_night"] = False
        game["witch_used_poison_this_night"] = False
        game["saved_players"] = set()  # 清空拯救记录
        
        self.game_manager.last_activity[room_id] = time.time()
        self.game_manager._save_game_file(room_id)
        
        # 发送白天开始消息
        await self._send_day_start_message(game, room_id)
        return True
    
    async def _process_cupid_action(self, game: Dict[str, Any], room_id: str):
        """处理丘比特行动"""
        cupid_action = game["night_actions"].get("cupid")
        if not cupid_action:
            return
        
        # 解析选择的两个玩家
        try:
            parts = cupid_action.split()
            if len(parts) < 2:
                return
                
            player1_num, player2_num = map(int, parts[:2])
            
            player1 = self._get_player_by_number(game, player1_num)
            player2 = self._get_player_by_number(game, player2_num)
            
            if player1 and player2 and player1["status"] == PlayerStatus.ALIVE.value and player2["status"] == PlayerStatus.ALIVE.value:
                # 设置情侣关系
                player1["is_lover"] = True
                player1["lover_partner"] = player2["qq"]
                player2["is_lover"] = True
                player2["lover_partner"] = player1["qq"]
                
                game["lovers"].extend([player1["qq"], player2["qq"]])
                
                # 通知情侣
                await self._send_private_message(game, player1["qq"],
                                               f"💕 你与玩家 {player2_num} 号 {player2['name']} 成为情侣！")
                await self._send_private_message(game, player2["qq"],
                                               f"💕 你与玩家 {player1_num} 号 {player1['name']} 成为情侣！")
                
        except (ValueError, IndexError):
            pass
    
    async def _process_guard_action(self, game: Dict[str, Any], room_id: str):
        """处理守卫行动"""
        guard_action = game["night_actions"].get("guard")
        if not guard_action:
            return
        
        try:
            target_num = int(guard_action)
            target_player = self._get_player_by_number(game, target_num)
            
            if target_player and target_player["status"] == PlayerStatus.ALIVE.value:
                # 检查是否连续两晚守护同一人
                if target_num != game.get("last_guard_target"):
                    game["guard_protected"] = target_num
                    game["last_guard_target"] = target_num
                    
                    guard_player = self._get_player_by_role(game, "guard")
                    if guard_player:
                        await self._send_private_message(game, guard_player["qq"],
                                                       f"🛡️ 你成功守护了玩家 {target_num} 号")
        except ValueError:
            pass
    
    async def _process_wolf_action(self, game: Dict[str, Any], room_id: str):
        """处理狼人行动"""
        wolf_kill_action = game["night_actions"].get("wolf_kill")
        if not wolf_kill_action:
            return
        
        try:
            target_num = int(wolf_kill_action)
            target_player = self._get_player_by_number(game, target_num)
            
            if target_player and target_player["status"] == PlayerStatus.ALIVE.value:
                # 检查守卫保护
                if target_num == game.get("guard_protected"):
                    # 被守护，不死亡
                    await self._send_group_message(game, 
                                                 f"🛡️ 玩家 {target_num} 号被守护，狼人袭击失败！")
                    return
                
                # 检查是否为双面人
                if target_player["role"] == "double_faced":
                    target_player["camp"] = Camp.WOLF
                    await self._send_private_message(game, target_player["qq"],
                                                   "🐺 你被狼人袭击，现在加入狼人阵营！")
                else:
                    # 检查是否被女巫拯救
                    if target_player["qq"] in game.get("saved_players", set()):
                        await self._send_group_message(game, 
                                                     f"💊 玩家 {target_num} 号被女巫拯救，狼人袭击失败！")
                        return
                    
                    # 加入死亡队列
                    game["death_queue"].append({
                        "player_qq": target_player["qq"],
                        "reason": DeathReason.WOLF_KILL.value,
                        "killer": "wolf"
                    })
        except ValueError:
            pass
    
    async def _process_seer_action(self, game: Dict[str, Any], room_id: str):
        """处理预言家行动"""
        seer_action = game["night_actions"].get("seer")
        if not seer_action:
            return
        
        try:
            target_num = int(seer_action)
            target_player = self._get_player_by_number(game, target_num)
            seer_player = self._get_player_by_role(game, "seer")
            
            if target_player and seer_player:
                target_role = target_player["role"]
                camp = ROLES[target_role]["camp"]
                
                result = "好人" if camp == Camp.VILLAGE else "狼人"
                await self._send_private_message(game, seer_player["qq"],
                                               f"🔮 玩家 {target_num} 号的阵营是: {result}")
        except ValueError:
            pass
    
    async def _process_witch_poison_action(self, game: Dict[str, Any], room_id: str):
        """处理女巫毒药行动"""
        witch_poison_action = game["night_actions"].get("witch_poison")
        if not witch_poison_action:
            return
        
        witch_player = self._get_player_by_role(game, "witch")
        if not witch_player:
            return
        
        try:
            target_num = int(witch_poison_action)
            target_player = self._get_player_by_number(game, target_num)
            
            if not target_player:
                return
            
            # 检查女巫是否有毒药
            if game["witch_status"] not in [WitchStatus.HAS_BOTH.value, WitchStatus.HAS_POISON_ONLY.value]:
                return
            
            # 标记毒药已使用
            game["witch_used_poison_this_night"] = True
            
            # 更新女巫状态
            if game["witch_status"] == WitchStatus.HAS_BOTH.value:
                game["witch_status"] = WitchStatus.HAS_SAVE_ONLY.value
            elif game["witch_status"] == WitchStatus.HAS_POISON_ONLY.value:
                game["witch_status"] = WitchStatus.USED_BOTH.value
            
            # 检查毒药是否有效
            if target_player["role"] in ["spiritualist", "double_faced"]:
                # 毒药无效，但不告知女巫
                await self._send_private_message(game, witch_player["qq"],
                                               f"☠️ 你对玩家 {target_num} 号使用了毒药")
                # 女巫不知道毒药无效
            else:
                # 毒药有效
                game["death_queue"].append({
                    "player_qq": target_player["qq"],
                    "reason": DeathReason.POISON.value,
                    "killer": witch_player["qq"]
                })
                await self._send_private_message(game, witch_player["qq"],
                                               f"☠️ 你使用毒药击杀了玩家 {target_num} 号")
                        
        except ValueError:
            pass
    
    async def _process_spiritualist_action(self, game: Dict[str, Any], room_id: str):
        """处理通灵师行动"""
        spiritualist_action = game["night_actions"].get("spiritualist")
        if not spiritualist_action:
            return
        
        try:
            target_num = int(spiritualist_action)
            target_player = self._get_player_by_number(game, target_num)
            spiritualist_player = self._get_player_by_role(game, "spiritualist")
            
            if target_player and spiritualist_player:
                role_name = ROLES[target_player["role"]]["name"]
                await self._send_private_message(game, spiritualist_player["qq"],
                                               f"👁️ 玩家 {target_num} 号的身份是: {role_name}")
        except ValueError:
            pass
    
    async def _process_magician_action(self, game: Dict[str, Any], room_id: str):
        """处理魔术师行动"""
        magician_action = game["night_actions"].get("magician")
        if not magician_action:
            return
        
        try:
            parts = magician_action.split()
            if len(parts) < 2:
                return
                
            num1, num2 = map(int, parts[:2])
            player1 = self._get_player_by_number(game, num1)
            player2 = self._get_player_by_number(game, num2)
            
            if player1 and player2:
                game["magician_swap"] = (num1, num2)
                magician_player = self._get_player_by_role(game, "magician")
                if magician_player:
                    await self._send_private_message(game, magician_player["qq"],
                                                   f"🎭 你交换了玩家 {num1} 号和 {num2} 号的号码牌")
        except (ValueError, IndexError):
            pass
    
    async def _process_painter_action(self, game: Dict[str, Any], room_id: str):
        """处理画皮行动"""
        painter_action = game["night_actions"].get("painter")
        if not painter_action:
            return
        
        try:
            target_num = int(painter_action)
            target_player = self._get_player_by_number(game, target_num)
            painter_player = self._get_player_by_role(game, "painter")
            
            if (target_player and painter_player and 
                target_player["status"] != PlayerStatus.ALIVE.value):
                # 画皮伪装成该玩家身份
                game["painter_disguised"] = target_player["role"]
                await self._send_private_message(game, painter_player["qq"],
                                               f"🎨 你成功伪装成 {ROLES[target_player['role']]['name']}")
        except ValueError:
            pass
    
    async def _execute_deaths(self, game: Dict[str, Any], room_id: str):
        """执行死亡"""
        death_messages = []
        
        for death in game["death_queue"]:
            player = game["players"][death["player_qq"]]
            if player["status"] == PlayerStatus.ALIVE.value:
                player["status"] = PlayerStatus.DEAD.value
                player["death_reason"] = death["reason"]
                player["killer"] = death["killer"]
                
                # 检查情侣殉情
                if player["is_lover"] and player["lover_partner"]:
                    lover = game["players"][player["lover_partner"]]
                    if lover["status"] == PlayerStatus.ALIVE.value:
                        lover["status"] = PlayerStatus.DEAD.value
                        lover["death_reason"] = DeathReason.LOVER_SUICIDE.value
                        lover["killer"] = player["qq"]
                        death_messages.append(f"💔 玩家 {lover['number']} 号 {lover['name']} 因情侣死亡而殉情")
                
                death_messages.append(f"💀 玩家 {player['number']} 号 {player['name']} 死亡")
        
        # 发送死亡消息
        if death_messages:
            await self._send_group_message(game, "夜晚死亡公告：\n" + "\n".join(death_messages))
        
        # 清空死亡队列
        game["death_queue"] = []
    
    async def process_vote(self, room_id: str) -> bool:
        """处理投票"""
        if room_id not in self.game_manager.games:
            return False
        
        game = self.game_manager.games[room_id]
        
        # 只统计存活玩家的投票
        alive_players = [p for p in game["players"].values() if p["status"] == PlayerStatus.ALIVE.value]
        total_alive = len(alive_players)
        voted_players = len([voter_qq for voter_qq in game["votes"].keys() 
                           if game["players"][voter_qq]["status"] == PlayerStatus.ALIVE.value])
        
        # 检查是否所有存活玩家都已完成投票
        if voted_players < total_alive:
            return False  # 还有玩家未投票
        
        # 计算投票结果
        vote_count = {}
        for voter_qq, vote_number in game["votes"].items():
            if game["players"][voter_qq]["status"] == PlayerStatus.ALIVE.value:
                vote_count[vote_number] = vote_count.get(vote_number, 0) + 1
        
        if not vote_count:
            # 无人投票，无人死亡
            await self._send_group_message(game, "今天无人被放逐。")
        else:
            # 找到最高票
            max_votes = max(vote_count.values())
            candidates = [num for num, count in vote_count.items() if count == max_votes]
            
            if len(candidates) > 1:
                # 平票，无人死亡
                await self._send_group_message(game, f"平票！今天无人被放逐。")
            else:
                # 放逐玩家
                exiled_number = candidates[0]
                exiled_player = None
                for player in game["players"].values():
                    if player["number"] == exiled_number and player["status"] == PlayerStatus.ALIVE.value:
                        exiled_player = player
                        break
                
                if exiled_player:
                    exiled_player["status"] = PlayerStatus.EXILED.value
                    exiled_player["death_reason"] = DeathReason.VOTE.value
                    
                    # 处理双面人阵营转换
                    if exiled_player["role"] == "double_faced":
                        exiled_player["camp"] = Camp.VILLAGE
                        await self._send_private_message(game, exiled_player["qq"], 
                                                       "你被投票放逐，现在加入好人阵营！")
                    
                    await self._send_group_message(game, 
                                                 f"玩家 {exiled_number} 号 {exiled_player['name']} 被放逐出局！")
        
        # 检查猎人技能
        for player in game["players"].values():
            if (player["status"] in [PlayerStatus.DEAD.value, PlayerStatus.EXILED.value] and 
                player["role"] == "hunter" and player["death_reason"] != DeathReason.POISON.value):
                game["phase"] = GamePhase.HUNTER_REVENGE.value
                game["phase_start_time"] = time.time()
                self.game_manager.last_activity[room_id] = time.time()
                self.game_manager._save_game_file(room_id)
                
                await self._send_private_message(game, player["qq"],
                                               "💥 复仇时间！你可以选择开枪带走一名玩家。使用命令: /wwg shoot <玩家号码>")
                return True
        
        # 进入夜晚
        game["phase"] = GamePhase.NIGHT.value
        game["day_count"] += 1
        game["phase_start_time"] = time.time()
        game["votes"] = {}
        game["night_actions"] = {}
        game["witch_save_candidates"] = []
        game["witch_used_save_this_night"] = False
        game["witch_used_poison_this_night"] = False
        self.game_manager.last_activity[room_id] = time.time()
        self.game_manager._save_game_file(room_id)
        
        await self._send_night_start_message(game, room_id)
        return True
    
    async def _check_game_end(self, game: Dict[str, Any], room_id: str) -> bool:
        """检查游戏是否结束"""
        # 统计各阵营存活人数
        village_alive = 0
        wolf_alive = 0
        third_party_alive = 0
        lovers_alive = 0
        
        for player in game["players"].values():
            if player["status"] != PlayerStatus.ALIVE.value:
                continue
            
            camp = ROLES[player["original_role"]]["camp"]
            if player["is_lover"]:
                lovers_alive += 1
            elif camp == Camp.VILLAGE:
                village_alive += 1
            elif camp == Camp.WOLF:
                wolf_alive += 1
            elif camp == Camp.THIRD_PARTY:
                third_party_alive += 1
        
        # 检查胜利条件
        if wolf_alive == 0:
            # 狼人全部死亡，村庄胜利
            game["winner"] = "village"
        elif wolf_alive >= village_alive + third_party_alive:
            # 狼人数量大于等于其他阵营总和，狼人胜利
            game["winner"] = "wolf"
        elif lovers_alive > 0 and village_alive + wolf_alive + third_party_alive == 0:
            # 只剩情侣存活，情侣胜利
            game["winner"] = "lover"
        elif third_party_alive > 0 and village_alive + wolf_alive + lovers_alive == 0:
            # 只剩第三方存活，第三方胜利
            game["winner"] = "third_party"
        else:
            return False
        
        # 游戏结束
        game["phase"] = GamePhase.ENDED.value
        game["ended_time"] = datetime.datetime.now().isoformat()
        
        # 发送游戏结果
        winner_text = {
            "village": "🏠 村庄阵营胜利！",
            "wolf": "🐺 狼人阵营胜利！",
            "lover": "💕 情侣阵营胜利！",
            "third_party": "🎭 第三方阵营胜利！"
        }.get(game["winner"], "游戏结束")
        
        result_message = f"🎮 游戏结束！{winner_text}\n\n玩家身份揭示：\n"
        
        for player in game["players"].values():
            role_name = ROLES[player["original_role"]]["name"]
            status = "存活" if player["status"] == PlayerStatus.ALIVE.value else "死亡"
            result_message += f"{player['number']}号 {player['name']} - {role_name} ({status})\n"
        
        await self._send_group_message(game, result_message)
        
        # 归档游戏
        game_code = self.game_manager.archive_game(room_id)
        if game_code:
            await self._send_group_message(game, f"📁 本局游戏已归档，对局码: {game_code}")
        
        return True
    
    def _get_player_by_number(self, game: Dict[str, Any], number: int) -> Optional[Dict[str, Any]]:
        """根据号码获取玩家"""
        for player in game["players"].values():
            if player["number"] == number:
                return player
        return None
    
    def _get_player_by_role(self, game: Dict[str, Any], role: str) -> Optional[Dict[str, Any]]:
        """根据角色获取玩家"""
        for player in game["players"].values():
            if player["role"] == role and player["status"] == PlayerStatus.ALIVE.value:
                return player
        return None
    
    def _get_role_action_key(self, role: str) -> str:
        """获取角色行动键"""
        action_keys = {
            "seer": "seer",
            "witch": "witch_poison",  # 女巫毒药行动键
            "wolf": "wolf_kill",
            "guard": "guard",
            "magician": "magician",
            "spiritualist": "spiritualist",
            "cupid": "cupid",
            "painter": "painter"
        }
        return action_keys.get(role, "")
    
    def _get_phase_timeout(self, phase: str) -> str:
        """获取阶段超时时间描述"""
        timeouts = {
            "night": "5分钟",
            "day": "5分钟", 
            "vote": "3分钟",
            "witch_save": "2分钟",
            "hunter_revenge": "2分钟"
        }
        return timeouts.get(phase, "5分钟")
    
    async def _send_private_message(self, game: Dict[str, Any], qq: str, message: str):
        """发送私聊消息 - 使用正确的API"""
        return await MessageSender.send_private_message(qq, message)
    
    async def _send_group_message(self, game: Dict[str, Any], message: str):
        """发送群聊消息 - 使用正确的API"""
        return await MessageSender.send_group_message(game["group_id"], message)
    
    async def _send_night_start_message(self, game: Dict[str, Any], room_id: str):
        """发送夜晚开始消息"""
        if game["day_count"] == 1:
            message = f"🌙 第 {game['day_count']} 夜（首夜）开始！\n请有夜晚行动能力的玩家使用相应命令行动。\n\n行动顺序：\n1. 丘比特（仅首夜）\n2. 守卫\n3. 狼人\n4. 女巫\n5. 预言家\n6. 通灵师\n7. 魔术师\n8. 画皮（第二夜起）\n\n⏰ 请在 {self._get_phase_timeout('night')} 内完成行动"
        else:
            message = f"🌙 第 {game['day_count']} 夜开始！请有夜晚行动能力的玩家使用相应命令行动。\n⏰ 请在 {self._get_phase_timeout('night')} 内完成行动"
        
        await self._send_group_message(game, message)
        
        # 私聊通知有行动的玩家
        for player in game["players"].values():
            if (player["status"] == PlayerStatus.ALIVE.value and
                ROLES[player["role"]]["night_action"]):
                
                role_info = ROLES[player["role"]]
                command = role_info["command"]
                description = role_info["description"]
                
                if command:
                    detailed_message = self._get_detailed_role_message(player, game)
                    await self._send_private_message(game, player["qq"], detailed_message)
    
    async def _send_day_start_message(self, game: Dict[str, Any], room_id: str):
        """发送白天开始消息"""
        if game["day_count"] == 1:
            message = f"☀️ 第 {game['day_count']} 天（首日）开始！\n请进行讨论和投票。\n使用 /wwg vote <玩家号码> 进行投票。\n\n💡 提示：首日发言请谨慎，注意观察其他玩家的发言行为。\n⏰ 请在 {self._get_phase_timeout('day')} 内完成讨论和投票"
        else:
            message = f"☀️ 第 {game['day_count']} 天开始！请进行讨论和投票。\n使用 /wwg vote <玩家号码> 进行投票。\n⏰ 请在 {self._get_phase_timeout('day')} 内完成讨论和投票"
        
        await self._send_group_message(game, message)
    
    def _get_detailed_role_message(self, player: Dict[str, Any], game: Dict[str, Any]) -> str:
        """获取详细的角色消息"""
        role = player["role"]
        role_info = ROLES[role]
        command = role_info["command"]
        
        # 计算已完成行动的玩家数量
        acted_count = len([p for p in game["players"].values() 
                          if p["has_acted"] and p["status"] == PlayerStatus.ALIVE.value])
        total_players = len([p for p in game["players"].values() if p["status"] == PlayerStatus.ALIVE.value])
        
        message = f"🌙 第 {game['day_count']} 夜行动\n"
        message += f"你的身份：{role_info['name']}\n"
        message += f"你的号码：{player['number']}号\n\n"
        message += f"🎯 角色能力：{role_info['description']}\n\n"
        
        # 特殊角色的额外信息
        if role == "witch":
            witch_status = game["witch_status"]
            status_text = {
                WitchStatus.HAS_BOTH.value: "💊 你有解药和毒药",
                WitchStatus.HAS_SAVE_ONLY.value: "💊 你只有解药",
                WitchStatus.HAS_POISON_ONLY.value: "☠️ 你只有毒药",
                WitchStatus.USED_BOTH.value: "❌ 你已无药可用"
            }.get(witch_status, "💊 状态未知")
            message += f"{status_text}\n\n"
        
        elif role == "wolf":
            # 显示狼队友信息
            wolf_teammates = []
            for p in game["players"].values():
                if (p["qq"] != player["qq"] and 
                    ROLES[p["role"]]["camp"] == Camp.WOLF and 
                    p["role"] != "hidden_wolf" and
                    p["status"] == PlayerStatus.ALIVE.value):
                    wolf_teammates.append(f"{p['number']}号")
            
            if wolf_teammates:
                message += f"🐺 你的狼队友：{', '.join(wolf_teammates)}\n\n"
            else:
                message += "🐺 你是唯一的狼人\n\n"
        
        elif role == "guard":
            last_target = game.get("last_guard_target")
            if last_target:
                message += f"🛡️ 上一夜你守护了 {last_target} 号玩家，今晚不能守护同一人\n\n"
        
        elif role == "painter" and game["day_count"] >= 2:
            message += "🎨 从第二夜开始，你可以伪装成已出局玩家的身份\n\n"
        
        message += f"📊 当前进度：{acted_count}/{total_players} 位玩家已完成行动\n\n"
        message += f"📝 使用命令：/wwg {command} <目标号码>\n"
        
        if role == "magician":
            message += "💡 示例：/wwg swap 3 5 （交换3号和5号）"
        elif role == "cupid":
            message += "💡 示例：/wwg choose 2 4 （选择2号和4号成为情侣）"
        else:
            message += "💡 示例：/wwg check 3 （查验3号玩家）"
        
        return message

# ==================== 测试命令 ====================
class TestPrivateMessageCommand(BaseCommand):
    """测试私聊消息发送命令"""
    
    command_name = "test_private"
    command_description = "测试向指定QQ号发送私聊消息"
    command_pattern = r"^/wwg test_private\s+(?P<qq>\d+)(?:\s+(?P<message>.+))?$"
    command_help = "用法: /wwg test_private <QQ号> [消息内容]"

    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        """执行测试私聊命令"""
        try:
            qq = self.matched_groups.get("qq", "").strip()
            message = self.matched_groups.get("message", "这是一条测试私聊消息").strip()
            
            if not qq:
                await self.send_text("❌ 请提供QQ号")
                return False, "缺少QQ号", True
            
            # 使用MessageSender发送私聊消息
            success = await MessageSender.send_private_message(qq, f"🐺 狼人杀插件测试消息:\n{message}")
            
            if success:
                await self.send_text(f"✅ 测试私聊消息已发送到 {qq}")
                return True, f"测试消息发送成功: {qq}", True
            else:
                await self.send_text(f"❌ 向 {qq} 发送测试消息失败，请检查QQ号是否正确或是否有私聊权限")
                return False, f"测试消息发送失败: {qq}", True
                
        except Exception as e:
            await self.send_text(f"❌ 测试命令执行出错: {str(e)}")
            return False, f"测试命令出错: {str(e)}", True

# ==================== 主命令处理器 ====================
class WerewolfGameCommand(BaseCommand):
    """狼人杀游戏命令"""
    
    command_name = "werewolf_game"
    command_description = "狼人杀游戏命令"
    command_pattern = r"^/wwg(\s+(?P<subcommand>\w+)(\s+(?P<args>.+))?)?$"
    command_help = (
        "🐺 狼人杀游戏命令帮助 🐺\n"
        "/wwg - 显示帮助\n"
        "/wwg host - 创建房间并自动加入\n"
        "/wwg join <房间号> - 加入房间\n"
        "/wwg status - 查看房间状态\n"
        "/wwg destroy - 销毁房间（仅房主）\n"
        "/wwg settings players <数量> - 设置玩家数(6-18)\n"
        "/wwg settings roles <角色> <数量> - 设置角色数量\n"
        "/wwg start - 开始游戏\n"
        "/wwg profile [QQ号] - 查看游戏档案\n"
        "/wwg archive <对局码> - 查询对局记录\n"
        "/wwg name set <昵称> - 设置游戏昵称\n"  # 新增
        "/wwg name view - 查看当前昵称\n"  # 新增
        "/wwg test_private <QQ号> [消息] - 测试私聊消息发送\n"
        "\n🎮 游戏内命令:\n"
        "/wwg check <号码> - 预言家查验\n"
        "/wwg save <号码> - 女巫使用解药\n"
        "/wwg poison <号码> - 女巫使用毒药\n"
        "/wwg kill <号码> - 狼人击杀\n"
        "/wwg guard <号码> - 守卫守护\n"
        "/wwg swap <号码1> <号码2> - 魔术师交换\n"
        "/wwg inspect <号码> - 通灵师查验\n"
        "/wwg choose <号码1> <号码2> - 丘比特选择情侣\n"
        "/wwg disguise <号码> - 画皮伪装\n"
        "/wwg vote <号码> - 投票\n"
        "/wwg shoot <号码> - 猎人开枪\n"
        "/wwg explode <号码> - 白狼王自爆\n"
        "/wwg skip - 跳过行动\n"
    )
    intercept_message = True
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.game_manager = WerewolfGameManager()
        self.game_processor = GameLogicProcessor(self.game_manager)
    
    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        """执行命令"""
        try:
            # 安全获取匹配组
            matched_groups = self.matched_groups or {}
            subcommand = matched_groups.get("subcommand")
            args = matched_groups.get("args")
            
            # 安全处理None值
            subcommand = subcommand.lower() if subcommand else ""
            args = args or ""
            
            # 特殊处理destroy命令，确保它被正确路由
            if subcommand == "destroy":
                return await self._destroy_game()
            
            if not subcommand:
                return await self._show_help()
            elif subcommand == "host":
                return await self._host_game()
            elif subcommand == "join":
                return await self._join_game(args)
            elif subcommand == "status":
                return await self._show_status()
            elif subcommand == "settings":
                return await self._handle_settings(args)
            elif subcommand == "start":
                return await self._start_game()
            elif subcommand == "profile":
                return await self._show_profile(args)
            elif subcommand == "archive":
                return await self._show_archive(args)
            elif subcommand == "test_private":
                return await self._handle_test_private(args)
            elif subcommand == "name":  # 新增昵称设置命令
                return await self._handle_name_command(args)
            else:
                # 游戏内行动命令
                return await self._handle_game_action(subcommand, args)
                
        except Exception as e:
            await self.send_text(f"❌ 命令执行出错: {str(e)}")
            return False, f"命令执行出错: {str(e)}", True
    
    async def _handle_test_private(self, args: str):
        """处理测试私聊命令"""
        try:
            parts = args.split(maxsplit=1)
            if not parts:
                await self.send_text("❌ 请提供QQ号，格式: /wwg test_private <QQ号> [消息]")
                return False, "缺少QQ号", True
            
            qq = parts[0].strip()
            message = parts[1].strip() if len(parts) > 1 else "这是一条测试私聊消息"
            
            if not qq:
                await self.send_text("❌ 请提供QQ号")
                return False, "缺少QQ号", True
            
            # 使用MessageSender发送私聊消息
            success = await MessageSender.send_private_message(qq, f"🐺 狼人杀插件测试消息:\n{message}")
            
            if success:
                await self.send_text(f"✅ 测试私聊消息已发送到 {qq}")
                return True, f"测试消息发送成功: {qq}", True
            else:
                await self.send_text(f"❌ 向 {qq} 发送测试消息失败，请检查QQ号是否正确或是否有私聊权限")
                return False, f"测试消息发送失败: {qq}", True
                
        except Exception as e:
            await self.send_text(f"❌ 测试命令执行出错: {str(e)}")
            return False, f"测试命令出错: {str(e)}", True
    
    async def _show_help(self):
        """显示帮助"""
        await self.send_text(self.command_help)
        return True, "显示帮助", True
    
    async def _host_game(self):
        
        """创建房间并自动加入房主"""
        user_id = self.message.message_info.user_info.user_id
        
        # 检查玩家是否有未完成的游戏
        if self._has_unfinished_game(str(user_id)):
            await self.send_text("❌ 你已有未完成的游戏，请先完成当前游戏或销毁房间")
            return False, "玩家有未完成游戏", True
        
        user_name = self._get_user_nickname(user_id)
        group_info = self.message.message_info.group_info
        
        if not group_info:
            await self.send_text("❌ 请在群聊中创建游戏房间")
            return False, "非群聊环境", True

        user_id = self.message.message_info.user_info.user_id
        user_name = self._get_user_nickname(user_id)
        group_info = self.message.message_info.group_info
        
        if not group_info:
            await self.send_text("❌ 请在群聊中创建游戏房间")
            return False, "非群聊环境", True
        
        group_id = group_info.group_id
        
        # 生成房间号
        room_id = f"WWG{int(time.time()) % 1000000:06d}"
        
        game = self.game_manager.create_game(room_id, str(user_id), str(group_id), user_name)
        
        if game:
            await self.send_text(
                f"🎮 狼人杀房间创建成功！\n"
                f"📍 房间号: {room_id}\n"
                f"👤 房主: {user_name} (已自动加入)\n"
                f"🎯 当前玩家: 1/{game['settings']['player_count']}\n"
                f"💡 使用 /wwg join {room_id} 加入游戏\n"
                f"📊 使用 /wwg status 查看房间状态\n"
                f"可用角色码\n"
                f"🏠 村庄阵营 (VILLAGE)\n"
                f"villager - 村民\seer - 预言家\witch - 女巫\hunter - 猎人\n"
                f"guard - 守卫\magician - 魔术师\spiritualist - 通灵师\successor - 继承者\n"
                f"🐺 狼人阵营 (WOLF)\n"
                f"wolf - 狼人\hidden_wolf - 隐狼\painter - 画皮\white_wolf - 白狼王\n"
                f"🎭 第三方阵营 (THIRD_PARTY)\n"
                f"double_faced - 双面人\cupid - 丘比特"
            )
            return True, f"创建房间 {room_id}", True
        else:
            await self.send_text("❌ 创建房间失败")
            return False, "创建房间失败", True
    
    async def _join_game(self, args):
        """加入游戏"""
        if not args:
            await self.send_text("❌ 请提供房间号，格式: /wwg join <房间号>")
            return False, "缺少房间号", True
        
        room_id = args.strip()
        user_id = self.message.message_info.user_info.user_id
        
        # 检查玩家是否有未完成的游戏
        if self._has_unfinished_game(str(user_id)):
            await self.send_text("❌ 你已有未完成的游戏，请先完成当前游戏或销毁房间")
            return False, "玩家有未完成游戏", True
        
        user_name = self._get_user_nickname(user_id)
        
        success = self.game_manager.join_game(room_id, str(user_id), user_name)
        
        if success:
            game = self.game_manager.games[room_id]
            await self.send_text(
                f"✅ 加入房间成功！\n"
                f"📍 房间号: {room_id}\n"
                f"🎯 当前玩家: {len(game['players'])}/{game['settings']['player_count']}\n"
                f"👤 你的号码: {game['players'][str(user_id)]['number']}"
            )
            return True, f"加入房间 {room_id}", True
        else:
            await self.send_text("❌ 加入房间失败，可能房间已满或不存在")
            return False, "加入房间失败", True
    
    async def _show_status(self):
        """显示房间状态"""
        user_id = self.message.message_info.user_info.user_id
        
        # 查找用户所在的游戏
        room_id = self._find_user_game(str(user_id))
        if not room_id:
            await self.send_text("❌ 你不在任何游戏中")
            return False, "用户不在游戏中", True
        
        game = self.game_manager.games[room_id]
        
        # 构建状态信息
        status_text = f"📊 房间状态 - {room_id}\n"
        status_text += f"👤 房主: {self._get_qq_nickname(game['host'])}\n"
        status_text += f"🎯 玩家: {len(game['players'])}/{game['settings']['player_count']}\n"
        status_text += f"📝 游戏阶段: {self._get_phase_display_name(game['phase'])}\n\n"
        
        # 玩家列表 - 修复：使用档案中的昵称而不是QQ号前五位
        status_text += "👥 当前玩家:\n"
        for player in game["players"].values():
            status_icon = "💚" if player["status"] == PlayerStatus.ALIVE.value else "💀"
            role_display = "???" if game["phase"] in [GamePhase.SETUP.value, GamePhase.NIGHT.value, GamePhase.DAY.value] else ROLES[player["original_role"]]["name"]
            # 使用玩家档案中的昵称
            player_nickname = player['name']
            status_text += f"  {player['number']}号 - {player_nickname} {status_icon}\n"
        
        status_text += "\n🎭 角色设置:\n"
        for role_id, count in game["settings"]["roles"].items():
            if count > 0:
                role_name = ROLES[role_id]["name"]
                status_text += f"  {role_name} ({role_id}): {count}个\n"
        
        await self.send_text(status_text)
        return True, "显示房间状态", True
    
    async def _handle_name_command(self, args: str):
        """处理昵称设置命令"""
        if not args:
            await self.send_text("❌ 请提供昵称操作，格式: /wwg name set <昵称> 或 /wwg name view")
            return False, "缺少昵称操作", True
        
        parts = args.split(maxsplit=1)
        operation = parts[0].lower()
        
        if operation == "set":
            if len(parts) < 2:
                await self.send_text("❌ 请提供要设置的昵称，格式: /wwg name set <昵称>")
                return False, "缺少昵称", True
            
            nickname = parts[1].strip()
            if len(nickname) > 20:
                await self.send_text("❌ 昵称长度不能超过20个字符")
                return False, "昵称过长", True
            if len(nickname) < 1:
                await self.send_text("❌ 昵称不能为空")
                return False, "昵称为空", True
            
            return await self._set_nickname(nickname)
        
        elif operation == "view":
            return await self._view_nickname()
        
        else:
            await self.send_text("❌ 未知的昵称操作，可用操作: set, view")
            return False, "未知昵称操作", True

    async def _set_nickname(self, nickname: str):
        """设置玩家昵称"""
        user_id = str(self.message.message_info.user_info.user_id)
        
        # 获取或创建玩家档案
        profile = self.game_manager.get_or_create_profile(user_id, nickname)
        
        # 更新昵称
        profile["name"] = nickname
        self.game_manager._save_profile(user_id)
        
        await self.send_text(f"✅ 昵称设置成功！\n你的新昵称: {nickname}")
        return True, f"设置昵称: {nickname}", True

    async def _view_nickname(self):
        """查看当前昵称"""
        user_id = str(self.message.message_info.user_info.user_id)
        profile = self.game_manager.player_profiles.get(user_id)
        
        if profile and profile.get("name"):
            await self.send_text(f"📝 你的当前昵称: {profile['name']}")
            return True, "查看昵称", True
        else:
            await self.send_text("❌ 你还没有设置昵称，使用 /wwg name set <昵称> 来设置")
            return False, "未设置昵称", True

    def _has_unfinished_game(self, user_id: str) -> bool:
        """检查玩家是否有未完成的游戏"""
        for room_id, game in self.game_manager.games.items():
            if user_id in game["players"] and game["phase"] != GamePhase.ENDED.value:
                return True
        return False

    def _get_user_nickname(self, user_id: str) -> str:
        """获取用户昵称 - 从玩家档案中获取"""
        try:
            profile = self.game_manager.player_profiles.get(str(user_id))
            if profile and profile.get("name"):
                return profile["name"]
            
            # 如果没有设置昵称，显示QQ号前五位
            return f"玩家{user_id[:5]}"
        except:
            return f"玩家{user_id[:5]}"
    
    def _get_qq_nickname(self, qq_number: str) -> str:
        """通过QQ号获取用户昵称"""
        try:
            # 导入必要的API
            from src.plugin_system.apis import person_api
            
            # 使用person_api获取用户信息
            person_id = person_api.get_person_id("qq", int(qq_number))
            
            # 由于get_person_value是异步的，我们需要在同步上下文中运行它
            import asyncio
            try:
                # 尝试获取现有的事件循环
                loop = asyncio.get_event_loop()
            except RuntimeError:
                # 如果没有事件循环，创建一个新的
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # 在事件循环中运行异步函数获取昵称
            nickname = loop.run_until_complete(
                person_api.get_person_value(person_id, "nickname")
            )
            
            if nickname:
                return nickname
            else:
                # 如果获取不到昵称，显示QQ号前五位
                return f"玩家{qq_number[:5]}"
                
        except Exception as e:
            print(f"获取QQ昵称失败 {qq_number}: {e}")
            # 出错时显示QQ号前五位
            return f"玩家{qq_number[:5]}"

    def _get_phase_display_name(self, phase: str) -> str:
        """获取阶段显示名称"""
        phase_names = {
            GamePhase.SETUP.value: "🛠️ 准备阶段",
            GamePhase.NIGHT.value: "🌙 夜晚阶段",
            GamePhase.DAY.value: "☀️ 白天阶段",
            GamePhase.VOTE.value: "🗳️ 投票阶段",
            GamePhase.HUNTER_REVENGE.value: "🔫 猎人复仇",
            GamePhase.WITCH_SAVE_PHASE.value: "💊 女巫救药",
            GamePhase.ENDED.value: "🎮 游戏结束"
        }
        return phase_names.get(phase, phase)
    
    async def _destroy_game(self):
        """销毁房间（任何阶段都可以）"""
        user_id = self.message.message_info.user_info.user_id
        
        # 查找用户所在的游戏
        room_id = self._find_user_game(str(user_id))
        if not room_id:
            await self.send_text("❌ 你不在任何游戏中")
            return False, "用户不在游戏中", True
        
        game = self.game_manager.games[room_id]
        
        # 检查房主权限
        if game["host"] != str(user_id):
            await self.send_text("❌ 只有房主可以销毁房间")
            return False, "非房主销毁房间", True
        
        success = self.game_manager.destroy_game(room_id)
        
        if success:
            await self.send_text(f"🗑️ 房间 {room_id} 已销毁，所有玩家已离开")
            return True, f"销毁房间 {room_id}", True
        else:
            await self.send_text("❌ 销毁房间失败")
            return False, "销毁房间失败", True
    
    async def _handle_settings(self, args):
        """处理设置命令"""
        if not args:
            await self.send_text("❌ 请提供设置参数")
            return False, "缺少设置参数", True
        
        parts = args.split()
        if len(parts) < 2:
            await self.send_text("❌ 设置命令格式错误")
            return False, "设置格式错误", True
        
        setting_type = parts[0]
        user_id = self.message.message_info.user_info.user_id
        
        # 查找用户所在的游戏
        room_id = self._find_user_game(str(user_id))
        if not room_id:
            await self.send_text("❌ 你不在任何游戏中")
            return False, "用户不在游戏中", True
        
        game = self.game_manager.games[room_id]
        
        # 检查房主权限
        if game["host"] != str(user_id):
            await self.send_text("❌ 只有房主可以修改设置")
            return False, "非房主修改设置", True
        
        # 修复：允许在准备阶段使用设置命令
        if game["phase"] != GamePhase.SETUP.value:
            await self.send_text(f"❌ 当前阶段不能执行此命令（当前阶段: {self._get_phase_display_name(game['phase'])}）")
            return False, "错误阶段设置", True
        
        if setting_type == "players":
            if len(parts) < 2:
                await self.send_text("❌ 请提供玩家数量")
                return False, "缺少玩家数量", True
            
            try:
                player_count = int(parts[1])
                if player_count < 6 or player_count > 18:
                    await self.send_text("❌ 玩家数量必须在6-18之间")
                    return False, "玩家数量超出范围", True
                
                game["settings"]["player_count"] = player_count
                self.game_manager._save_game_file(room_id)
                
                await self.send_text(f"✅ 设置玩家数量为: {player_count}")
                return True, f"设置玩家数量为 {player_count}", True
                
            except ValueError:
                await self.send_text("❌ 玩家数量必须是数字")
                return False, "玩家数量非数字", True
        
        elif setting_type == "roles":
            if len(parts) < 3:
                await self.send_text("❌ 请提供角色和数量，格式: /wwg settings roles <角色> <数量>")
                return False, "缺少角色参数", True
            
            role_key = parts[1]
            if role_key not in ROLES:
                await self.send_text(f"❌ 未知角色: {role_key}")
                return False, f"未知角色: {role_key}", True
            
            try:
                role_count = int(parts[2])
                if role_count < 0:
                    await self.send_text("❌ 角色数量不能为负数")
                    return False, "角色数量为负", True
                
                game["settings"]["roles"][role_key] = role_count
                self.game_manager._save_game_file(room_id)
                
                role_name = ROLES[role_key]["name"]
                await self.send_text(f"✅ 设置 {role_name} ({role_key}) 数量为: {role_count}")
                return True, f"设置 {role_key} 数量为 {role_count}", True
                
            except ValueError:
                await self.send_text("❌ 角色数量必须是数字")
                return False, "角色数量非数字", True
        
        else:
            await self.send_text("❌ 未知设置类型")
            return False, "未知设置类型", True
    
    async def _start_game(self):
        """开始游戏"""
        user_id = self.message.message_info.user_info.user_id
        
        # 查找用户所在的游戏
        room_id = self._find_user_game(str(user_id))
        if not room_id:
            await self.send_text("❌ 你不在任何游戏中")
            return False, "用户不在游戏中", True
        
        game = self.game_manager.games[room_id]
        
        # 检查房主权限
        if game["host"] != str(user_id):
            await self.send_text("❌ 只有房主可以开始游戏")
            return False, "非房主开始游戏", True
        
        success = self.game_manager.start_game(room_id)
        
        if success:
            # 发送首夜开始消息到群聊
            await self._send_group_message(game, 
                "🎮 游戏开始！\n"
                "🌙 首夜降临，请有夜晚行动能力的玩家查看私聊消息获取角色信息并行动。\n"
                "💡 行动顺序：无顺序，若女巫需要考虑解药请选择跳过毒药行动，后续会有独立的解药阶段以供放药\n"
                "⏰ 请在 5分钟 内完成行动"
            )
            
            # 私聊发送详细的角色信息给所有玩家
            for player_qq, player in game["players"].items():
                role = player["role"]
                role_info = ROLES[role]
                
                message = f"🎮 游戏开始！\n\n"
                message += f"📍 房间号: {room_id}\n"
                message += f"🎯 你的身份: {role_info['name']}\n"
                message += f"🔢 你的号码: {player['number']}号\n\n"
                message += f"📖 角色描述: {role_info['description']}\n\n"
                
                # 特殊角色的额外信息
                if role_info["camp"] == Camp.WOLF and role != "hidden_wolf":
                    # 显示狼队友信息
                    wolf_teammates = []
                    for p in game["players"].values():
                        if (p["qq"] != player_qq and 
                            ROLES[p["role"]]["camp"] == Camp.WOLF and 
                            p["role"] != "hidden_wolf"):
                            wolf_teammates.append(f"{p['number']}号 {p['name']}")
                    
                    if wolf_teammates:
                        message += f"🐺 你的狼队友:\n"
                        for teammate in wolf_teammates:
                            message += f"  • {teammate}\n"
                        message += "\n"
                
                if role_info["command"]:
                    if role == "magician":
                        message += f"📝 使用命令: /wwg {role_info['command']} <号码1> <号码2>\n"
                        message += f"💡 示例: /wwg swap 3 5 （交换3号和5号）"
                    elif role == "cupid":
                        message += f"📝 使用命令: /wwg {role_info['command']} <号码1> <号码2>\n"
                        message += f"💡 示例: /wwg choose 2 4 （选择2号和4号成为情侣）"
                    else:
                        message += f"📝 使用命令: /wwg {role_info['command']} <目标号码>\n"
                        message += f"💡 示例: /wwg check 3 （查验3号玩家）"
                
                await MessageSender.send_private_message(player_qq, message)
            
            return True, "游戏开始", True
        else:
            await self.send_text("❌ 开始游戏失败，玩家数量不足或角色分配错误")
            return False, "开始游戏失败", True
    
    async def _show_profile(self, args):
        """显示玩家档案"""
        target_qq = args.strip() if args else str(self.message.message_info.user_info.user_id)
        
        profile = self.game_manager.player_profiles.get(target_qq)
        if not profile:
            await self.send_text("❌ 未找到该玩家的游戏档案")
            return False, "未找到玩家档案", True
        
        profile_text = (
            f"📊 玩家档案 - {profile['name']} (QQ: {profile['qq']})\n"
            f"总对局数: {profile['total_games']}\n"
            f"胜利: {profile['wins']} | 失败: {profile['losses']}\n"
            f"胜率: {profile['wins'] / profile['total_games'] * 100 if profile['total_games'] > 0 else 0:.1f}%\n"
            f"最近10场胜率: {profile['recent_win_rate'] * 100:.1f}%\n"
            f"击杀数: {profile['kills']} | 票杀数: {profile['votes']}"
        )
        
        await self.send_text(profile_text)
        return True, "显示玩家档案", True
    
    async def _show_archive(self, args):
        """显示对局记录"""
        if not args:
            await self.send_text("❌ 请提供对局码，格式: /wwg archive <对局码>")
            return False, "缺少对局码", True
        
        game_code = args.strip()
        game = self.game_manager.get_archived_game(game_code)
        
        if not game:
            await self.send_text("❌ 未找到该对局记录")
            return False, "未找到对局记录", True
        
        archive_text = f"📁 对局记录 - {game_code}\n"
        archive_text += f"房间号: {game['room_id']}\n"
        archive_text += f"开始时间: {game['started_time']}\n"
        archive_text += f"结束时间: {game['ended_time']}\n"
        archive_text += f"胜利阵营: {game['winner']}\n\n"
        archive_text += "玩家信息:\n"
        
        for player in game["players"].values():
            role_name = ROLES[player["original_role"]]["name"]
            status = "存活" if player["status"] == PlayerStatus.ALIVE.value else "死亡"
            archive_text += f"{player['number']}号 {player['name']} - {role_name} ({status})\n"
        
        await self.send_text(archive_text)
        return True, "显示对局记录", True
    
    async def _handle_game_action(self, action: str, args: str):
        """处理游戏内行动命令"""
        user_id = str(self.message.message_info.user_info.user_id)
        
        # 特殊处理：destroy命令不受游戏阶段限制
        if action == "destroy":
            return await self._destroy_game()
        
        user_id = str(self.message.message_info.user_info.user_id)

        # 查找用户所在的游戏
        room_id = self._find_user_game(user_id)
        if not room_id:
            await self.send_text("❌ 你不在任何游戏中")
            return False, "用户不在游戏中", True
        
        game = self.game_manager.games[room_id]
        player = game["players"].get(user_id)
        
        if not player:
            await self.send_text("❌ 你不在游戏中")
            return False, "玩家不在游戏中", True
        
        if player["status"] != PlayerStatus.ALIVE.value:
            await self.send_text("❌ 你已出局，无法执行行动")
            return False, "玩家已出局", True
        
        # 检查游戏阶段
        current_phase = game["phase"]
        
        # 女巫解药阶段特殊处理
        if current_phase == GamePhase.WITCH_SAVE_PHASE.value:
            if action == "save":
                return await self._handle_witch_save_action(game, player, args, room_id)
            elif action == "skip":
                return await self._handle_witch_skip_action(game, player, room_id)
            else:
                await self.send_text("❌ 当前处于女巫解药阶段，只能使用 save 或 skip 命令")
                return False, "错误阶段命令", True
        
        # 夜晚行动
        if current_phase == GamePhase.NIGHT.value:
            return await self._handle_night_action(game, player, action, args, room_id)
        
        # 白天投票
        elif current_phase == GamePhase.DAY.value:
            if action == "vote":
                return await self._handle_vote_action(game, player, args, room_id)
            elif action == "explode":
                return await self._handle_white_wolf_action(game, player, args, room_id)
            else:
                await self.send_text("❌ 白天只能进行投票或白狼王自爆")
                return False, "白天错误命令", True
        
        # 猎人复仇
        elif current_phase == GamePhase.HUNTER_REVENGE.value:
            if action == "shoot":
                return await self._handle_hunter_action(game, player, args, room_id)
            else:
                await self.send_text("❌ 当前只能使用 shoot 命令")
                return False, "猎人阶段错误命令", True
        
        else:
            await self.send_text(f"❌ 当前阶段不能执行此命令（当前阶段: {self._get_phase_display_name(current_phase)}）")
            return False, "阶段错误", True
    
    async def _handle_night_action(self, game: Dict[str, Any], player: Dict[str, Any], action: str, args: str, room_id: str):
        """处理夜晚行动"""
        role = player["role"]
        role_info = ROLES[role]
        
        # 检查角色是否有夜晚行动能力
        if not role_info["night_action"]:
            await self.send_text("❌ 你的角色没有夜晚行动能力")
            return False, "角色无夜晚行动", True
        
        # 检查命令是否匹配角色
        expected_command = role_info["command"]
        if action != expected_command and not (role == "witch" and action in ["save", "poison"]):
            await self.send_text(f"❌ 你的角色应该使用命令: /wwg {expected_command}")
            return False, "角色命令不匹配", True
        
        # 女巫特殊处理
        if role == "witch":
            if action == "save":
                await self.send_text("❌ 解药将在其他玩家行动完成后进入就绪阶段使用")
                return False, "女巫解药未就绪", True
            elif action == "poison":
                # 检查女巫是否有毒药
                if game["witch_status"] not in [WitchStatus.HAS_BOTH.value, WitchStatus.HAS_POISON_ONLY.value]:
                    await self.send_text("❌ 你已经没有毒药了")
                    return False, "女巫无毒药", True
                
                if not args:
                    await self.send_text("❌ 请提供目标号码，格式: /wwg poison <号码>")
                    return False, "女巫毒药缺少目标", True
                
                try:
                    target_num = int(args)
                    target_player = self._get_player_by_number(game, target_num)
                    if not target_player or target_player["status"] != PlayerStatus.ALIVE.value:
                        await self.send_text("❌ 目标玩家不存在或已出局")
                        return False, "女巫毒药目标无效", True
                    
                    game["night_actions"]["witch_poison"] = args
                    player["has_acted"] = True
                    self.game_manager.last_activity[room_id] = time.time()
                    self.game_manager._save_game_file(room_id)
                    
                    # 计算行动进度
                    acted_count = len([p for p in game["players"].values() 
                                      if p["has_acted"] and p["status"] == PlayerStatus.ALIVE.value])
                    total_players = len([p for p in game["players"].values() if p["status"] == PlayerStatus.ALIVE.value])
                    
                    await self.send_text(f"✅ 已记录毒药目标: {args}号\n📊 当前进度: {acted_count}/{total_players} 位玩家已完成行动")
                    
                    # 检查是否需要进入女巫解药阶段
                    await self.game_processor.process_night_actions(room_id)
                    
                    return True, "女巫使用毒药", True
                    
                except ValueError:
                    await self.send_text("❌ 目标号码必须是数字")
                    return False, "女巫毒药目标非数字", True
        
        # 其他角色行动
        else:
            if not args:
                await self.send_text(f"❌ 请提供目标号码，格式: /wwg {action} <号码>")
                return False, f"{role}缺少目标", True
            
            try:
                # 特殊命令处理
                if action == "swap" or action == "choose":
                    parts = args.split()
                    if len(parts) < 2:
                        await self.send_text(f"❌ 请提供两个号码，格式: /wwg {action} <号码1> <号码2>")
                        return False, f"{role}缺少目标", True
                    
                    target1 = int(parts[0])
                    target2 = int(parts[1])
                    
                    target_player1 = self._get_player_by_number(game, target1)
                    target_player2 = self._get_player_by_number(game, target2)
                    
                    if not target_player1 or target_player1["status"] != PlayerStatus.ALIVE.value:
                        await self.send_text("❌ 第一个目标玩家不存在或已出局")
                        return False, f"{role}目标1无效", True
                    if not target_player2 or target_player2["status"] != PlayerStatus.ALIVE.value:
                        await self.send_text("❌ 第二个目标玩家不存在或已出局")
                        return False, f"{role}目标2无效", True
                    
                    game["night_actions"][self._get_role_action_key(role)] = f"{target1} {target2}"
                    
                else:
                    target_num = int(args)
                    target_player = self._get_player_by_number(game, target_num)
                    if not target_player or target_player["status"] != PlayerStatus.ALIVE.value:
                        await self.send_text("❌ 目标玩家不存在或已出局")
                        return False, f"{role}目标无效", True
                    
                    game["night_actions"][self._get_role_action_key(role)] = args
                
                player["has_acted"] = True
                self.game_manager.last_activity[room_id] = time.time()
                self.game_manager._save_game_file(room_id)
                
                # 计算行动进度
                acted_count = len([p for p in game["players"].values() 
                                  if p["has_acted"] and p["status"] == PlayerStatus.ALIVE.value])
                total_players = len([p for p in game["players"].values() if p["status"] == PlayerStatus.ALIVE.value])
                
                await self.send_text(f"✅ 行动已记录: {action} {args}\n📊 当前进度: {acted_count}/{total_players} 位玩家已完成行动")
                
                # 检查是否需要进入女巫解药阶段
                await self.game_processor.process_night_actions(room_id)
                
                return True, f"{role}行动记录", True
                
            except ValueError:
                await self.send_text("❌ 目标号码必须是数字")
                return False, f"{role}目标非数字", True
        
        return False, "未处理行动", True
    
    async def _handle_witch_save_action(self, game: Dict[str, Any], player: Dict[str, Any], args: str, room_id: str):
        """处理女巫解药行动"""
        if player["role"] != "witch":
            await self.send_text("❌ 只有女巫可以使用解药")
            return False, "非女巫使用解药", True
        
        if not args:
            await self.send_text("❌ 请提供目标号码，格式: /wwg save <号码>")
            return False, "女巫解药缺少目标", True
        
        try:
            target_num = int(args)
            # 检查目标是否在候选列表中
            candidate_numbers = [num for num, _ in game["witch_save_candidates"]]
            if target_num not in candidate_numbers:
                await self.send_text("❌ 目标不在可拯救的玩家列表中")
                return False, "女巫解药目标无效", True
            
            game["night_actions"]["witch_save"] = args
            self.game_manager.last_activity[room_id] = time.time()
            self.game_manager._save_game_file(room_id)
            
            # 处理女巫解药阶段
            await self.game_processor.process_witch_save_phase(room_id)
            return True, "女巫使用解药", True
            
        except ValueError:
            await self.send_text("❌ 目标号码必须是数字")
            return False, "女巫解药目标非数字", True
    
    async def _handle_witch_skip_action(self, game: Dict[str, Any], player: Dict[str, Any], room_id: str):
        """处理女巫跳过解药行动"""
        if player["role"] != "witch":
            await self.send_text("❌ 只有女巫可以跳过解药")
            return False, "非女巫跳过解药", True
        
        game["night_actions"]["witch_skip"] = "true"
        self.game_manager.last_activity[room_id] = time.time()
        self.game_manager._save_game_file(room_id)
        
        # 处理女巫解药阶段
        await self.game_processor.process_witch_save_phase(room_id)
        return True, "女巫跳过解药", True
    
    async def _handle_vote_action(self, game: Dict[str, Any], player: Dict[str, Any], args: str, room_id: str):
        """处理投票行动"""
        if not args:
            await self.send_text("❌ 请提供投票目标，格式: /wwg vote <号码>")
            return False, "投票缺少目标", True
        
        try:
            vote_target = int(args)
            target_player = self._get_player_by_number(game, vote_target)
            if not target_player or target_player["status"] != PlayerStatus.ALIVE.value:
                await self.send_text("❌ 目标玩家不存在或已出局")
                return False, "投票目标无效", True
            
            # 检查是否已经投过票
            previous_vote = game["votes"].get(player["qq"])
            if previous_vote:
                # 更换投票目标
                game["votes"][player["qq"]] = vote_target
                await self.send_text(f"✅ 已更换投票目标为 {vote_target} 号玩家（原投票: {previous_vote} 号）")
            else:
                # 第一次投票
                game["votes"][player["qq"]] = vote_target
                await self.send_text(f"✅ 已投票给 {vote_target} 号玩家")
            
            # 计算投票进度
            alive_players = [p for p in game["players"].values() if p["status"] == PlayerStatus.ALIVE.value]
            total_alive = len(alive_players)
            voted_players = len([voter_qq for voter_qq in game["votes"].keys() 
                               if game["players"][voter_qq]["status"] == PlayerStatus.ALIVE.value])
            
            await self.send_text(f"📊 投票进度: {voted_players}/{total_alive} 位存活玩家已完成投票")
            
            self.game_manager.last_activity[room_id] = time.time()
            self.game_manager._save_game_file(room_id)
            
            # 检查是否所有玩家都已完成投票
            await self.game_processor.process_vote(room_id)
            
            return True, f"投票给 {vote_target}", True
        except ValueError:
            await self.send_text("❌ 投票目标必须是数字")
            return False, "投票目标非数字", True
    
    async def _handle_white_wolf_action(self, game: Dict[str, Any], player: Dict[str, Any], args: str, room_id: str):
        """处理白狼王自爆行动"""
        if player["role"] != "white_wolf":
            await self.send_text("❌ 只有白狼王可以自爆")
            return False, "非白狼王自爆", True
        
        if not args:
            await self.send_text("❌ 请提供自爆目标，格式: /wwg explode <号码>")
            return False, "自爆缺少目标", True
        
        try:
            target_num = int(args)
            target_player = self._get_player_by_number(game, target_num)
            
            if not target_player or target_player["status"] != PlayerStatus.ALIVE.value:
                await self.send_text("❌ 目标玩家不存在或已出局")
                return False, "自爆目标无效", True
            
            # 白狼王和目标一起死亡
            player["status"] = PlayerStatus.DEAD.value
            player["death_reason"] = DeathReason.WHITE_WOLF.value
            player["killer"] = player["qq"]
            
            target_player["status"] = PlayerStatus.DEAD.value
            target_player["death_reason"] = DeathReason.WHITE_WOLF.value
            target_player["killer"] = player["qq"]
            
            game["white_wolf_exploded"] = True
            
            await self._send_group_message(game, 
                                         f"💥 白狼王 {player['number']} 号自爆，带走了 {target_num} 号玩家！")
            
            # 立即进入夜晚
            game["phase"] = GamePhase.NIGHT.value
            game["day_count"] += 1
            game["phase_start_time"] = time.time()
            game["votes"] = {}
            game["night_actions"] = {}
            self.game_manager.last_activity[room_id] = time.time()
            self.game_manager._save_game_file(room_id)
            
            await self._send_night_start_message(game, room_id)
            return True, "白狼王自爆", True
            
        except ValueError:
            await self.send_text("❌ 自爆目标必须是数字")
            return False, "自爆目标非数字", True
    
    async def _handle_hunter_action(self, game: Dict[str, Any], player: Dict[str, Any], args: str, room_id: str):
        """处理猎人开枪行动"""
        if player["role"] != "hunter":
            await self.send_text("❌ 只有猎人可以开枪")
            return False, "非猎人开枪", True
        
        if not args:
            await self.send_text("❌ 请提供开枪目标，格式: /wwg shoot <号码>")
            return False, "开枪缺少目标", True
        
        try:
            target_num = int(args)
            target_player = self._get_player_by_number(game, target_num)
            
            if not target_player or target_player["status"] != PlayerStatus.ALIVE.value:
                await self.send_text("❌ 目标玩家不存在或已出局")
                return False, "开枪目标无效", True
            
            # 猎人开枪击杀目标
            target_player["status"] = PlayerStatus.DEAD.value
            target_player["death_reason"] = DeathReason.HUNTER_SHOOT.value
            target_player["killer"] = player["qq"]
            
            await self._send_group_message(game, 
                                         f"🔫 猎人 {player['number']} 号开枪带走了 {target_num} 号玩家！")
            
            # 进入夜晚
            game["phase"] = GamePhase.NIGHT.value
            game["day_count"] += 1
            game["phase_start_time"] = time.time()
            game["votes"] = {}
            game["night_actions"] = {}
            self.game_manager.last_activity[room_id] = time.time()
            self.game_manager._save_game_file(room_id)
            
            await self._send_night_start_message(game, room_id)
            return True, "猎人开枪", True
            
        except ValueError:
            await self.send_text("❌ 开枪目标必须是数字")
            return False, "开枪目标非数字", True
    
    def _find_user_game(self, user_id: str) -> Optional[str]:
        """查找用户所在的游戏房间"""
        for room_id, game in self.game_manager.games.items():
            if user_id in game["players"]:
                return room_id
        return None
    
    def _get_player_by_number(self, game: Dict[str, Any], number: int) -> Optional[Dict[str, Any]]:
        """根据号码获取玩家"""
        for player in game["players"].values():
            if player["number"] == number:
                return player
        return None
    
    def _get_role_action_key(self, role: str) -> str:
        """获取角色行动键"""
        action_keys = {
            "seer": "seer",
            "witch": "witch_poison",
            "wolf": "wolf_kill",
            "guard": "guard",
            "magician": "magician",
            "spiritualist": "spiritualist",
            "cupid": "cupid",
            "painter": "painter"
        }
        return action_keys.get(role, "")
    
    async def _send_private_message(self, game: Dict[str, Any], qq: str, message: str):
        """发送私聊消息 - 使用正确的API"""
        return await MessageSender.send_private_message(qq, message)
    
    async def _send_group_message(self, game: Dict[str, Any], message: str):
        """发送群聊消息 - 使用正确的API"""
        return await MessageSender.send_group_message(game["group_id"], message)
    
    async def _send_night_start_message(self, game: Dict[str, Any], room_id: str):
        """发送夜晚开始消息"""
        message = f"🌙 第 {game['day_count']} 夜开始！请有夜晚行动能力的玩家使用相应命令行动。"
        await self._send_group_message(game, message)

# ==================== 主插件类 ====================
@register_plugin
class WerewolfGamePlugin(BasePlugin):
    """狼人杀游戏插件"""
    
    plugin_name = "Werewolves-Master-Plugin"
    plugin_description = "纯指令驱动的狼人杀游戏插件"
    plugin_version = "1.0.0"
    plugin_author = "KArabella"
    enable_plugin = True
    dependencies = []
    python_dependencies = []
    config_file_name = "config.toml"
    
    config_section_descriptions = {
        "plugin": "插件基础配置",
        "game": "游戏设置"
    }
    
    config_schema = {
        "plugin": {
            "enabled": ConfigField(type=bool, default=True, description="是否启用插件"),
            "max_players": ConfigField(type=int, default=18, description="最大玩家数"),
            "min_players": ConfigField(type=int, default=6, description="最小玩家数")
        },
        "game": {
            "night_duration": ConfigField(type=int, default=300, description="夜晚持续时间(秒)"),
            "day_duration": ConfigField(type=int, default=300, description="白天持续时间(秒)"),
            "inactive_timeout": ConfigField(type=int, default=1200, description="不活动超时时间(秒)")
        }
    }
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.game_manager = WerewolfGameManager()
        self.cleanup_task = None
    
    async def on_enable(self):
        """插件启用时"""
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    async def on_disable(self):
        """插件禁用时"""
        if self.cleanup_task:
            self.cleanup_task.cancel()
    
    async def _cleanup_loop(self):
        """清理循环"""
        while True:
            try:
                self.game_manager.cleanup_inactive_games()
                await asyncio.sleep(60)  # 每分钟检查一次
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"清理循环错误: {e}")
    
    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        """返回插件组件"""
        return [
            (WerewolfGameCommand.get_command_info(), WerewolfGameCommand),
            (TestPrivateMessageCommand.get_command_info(), TestPrivateMessageCommand)
        ]