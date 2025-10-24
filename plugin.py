import os
import json
import time
import random
import asyncio
import logging
from typing import List, Tuple, Type, Dict, Any, Optional, Set
from datetime import datetime
from src.plugin_system import (
    BasePlugin,
    register_plugin,
    BaseCommand,
    ComponentInfo,
    ConfigField,
)

# ================= 全局状态 =================
active_games: Dict[str, Dict] = {}
player_profiles: Dict[str, Dict] = {}
game_archives: Dict[str, Dict] = {}
loaded_extensions: Dict[str, Dict] = {}

# 创建日志器
logger = logging.getLogger("WerewolfGame")

# ================= 基础角色定义 =================
BASE_ROLES = {
    "VILL": {
        "name": "村民", "team": "village", "night_action": False, "day_action": False,
        "description": "普通村民，没有特殊能力"
    },
    "SEER": {
        "name": "预言家", "team": "village", "night_action": True, "day_action": False,
        "description": "每晚可以查验一名玩家的阵营",
        "commands": {"check": "查验玩家身份"}
    },
    "WITCH": {
        "name": "女巫", "team": "village", "night_action": True, "day_action": False,
        "description": "拥有一瓶解药和一瓶毒药，每晚只能使用一瓶",
        "commands": {"heal": "使用解药", "poison": "使用毒药", "skip": "跳过行动"}
    },
    "HUNT": {
        "name": "猎人", "team": "village", "night_action": False, "day_action": True,
        "description": "死亡时可以开枪带走一名玩家",
        "commands": {"shoot": "选择射击目标"}
    },
    "WOLF": {
        "name": "狼人", "team": "wolf", "night_action": True, "day_action": False,
        "description": "每晚与其他狼人讨论并选择击杀目标",
        "commands": {"kill": "选择击杀目标", "skip": "跳过行动"}
    }
}

# ================= 扩展角色定义 =================
EXTENSION_ROLES = {
    "HWOLF": {
        "name": "隐狼", "team": "wolf", "night_action": False, "day_action": False,
        "description": "潜伏在好人中的狼。被预言家查验时显示为好人。不能自爆，不能参与狼人夜间的杀人。当其他所有狼人队友出局后，隐狼获得刀人能力。"
    },
    "GUARD": {
        "name": "守卫", "team": "village", "night_action": True, "day_action": False,
        "description": "每晚可以守护一名玩家（包括自己），使其免于狼人的袭击。不能连续两晚守护同一名玩家。",
        "commands": {"guard": "守护玩家"}
    },
    "MAGI": {
        "name": "魔术师", "team": "village", "night_action": True, "day_action": False,
        "description": "每晚可以选择交换两名玩家的号码牌，持续到下一个夜晚。当晚所有以他们为目标的技能效果都会被交换。",
        "commands": {"swap": "交换玩家号码牌"}
    },
    "DUAL": {
        "name": "双面人", "team": "third", "night_action": False, "day_action": False,
        "description": "游戏开始时无固定阵营。当成为狼人的击杀目标时，加入狼人阵营。当被投票放逐时，加入好人阵营。女巫的毒药对他无效。"
    },
    "PSYC": {
        "name": "通灵师", "team": "village", "night_action": True, "day_action": False,
        "description": "每晚可以查验一名玩家的具体身份。代价：通灵师无法被守卫守护，且女巫的解药对其无效。",
        "commands": {"check": "查验具体身份"}
    },
    "INHE": {
        "name": "继承者", "team": "village", "night_action": False, "day_action": False,
        "description": "当相邻的玩家有神民出局时，继承者会秘密获得该神民的技能，并晋升为神民。"
    },
    "PAINT": {
        "name": "画皮", "team": "wolf", "night_action": True, "day_action": False,
        "description": "游戏第二夜起，可以潜入一名已出局玩家的身份，之后被预言家查验时，会显示为该已出局玩家的具体身份。每局限一次。",
        "commands": {"paint": "伪装身份"}
    },
    "WWOLF": {
        "name": "白狼王", "team": "wolf", "night_action": False, "day_action": True,
        "description": "白天投票放逐阶段，可以随时翻牌自爆，并带走一名玩家。此行动会立即终止当天发言并进入黑夜。",
        "commands": {"explode": "自爆并带走玩家"}
    },
    "CUPID": {
        "name": "丘比特", "team": "third", "night_action": True, "day_action": False,
        "description": "游戏第一晚，选择两名玩家成为情侣。丘比特与情侣形成第三方阵营。情侣中若有一方死亡，另一方会立即殉情。",
        "commands": {"connect": "连接情侣"}
    }
}

class GameManager:
    """游戏管理器"""
    
    def __init__(self, plugin):
        self.plugin = plugin
        self._ensure_directories()
        self._load_profiles()
        self._load_archives()
        self._load_extensions()
    
    def _ensure_directories(self):
        """确保必要的目录存在"""
        os.makedirs("plugins/Werewolves-Master-Plugin/games/finished", exist_ok=True)
        os.makedirs("plugins/Werewolves-Master-Plugin/users", exist_ok=True)
        os.makedirs("plugins/Werewolves-Master-Plugin/extensions", exist_ok=True)
    
    def _load_profiles(self):
        """加载玩家档案"""
        global player_profiles
        profile_dir = "plugins/Werewolves-Master-Plugin/users"
        if os.path.exists(profile_dir):
            for filename in os.listdir(profile_dir):
                if filename.endswith(".json"):
                    qq = filename[:-5]
                    try:
                        with open(os.path.join(profile_dir, filename), 'r', encoding='utf-8') as f:
                            player_profiles[qq] = json.load(f)
                    except Exception as e:
                        logger.error(f"加载玩家档案 {filename} 失败: {e}")
    
    def _load_archives(self):
        """加载游戏存档"""
        global game_archives
        archive_dir = "plugins/Werewolves-Master-Plugin/games/finished"
        if os.path.exists(archive_dir):
            for filename in os.listdir(archive_dir):
                if filename.endswith(".json"):
                    archive_code = filename[:-5]
                    try:
                        with open(os.path.join(archive_dir, filename), 'r', encoding='utf-8') as f:
                            game_archives[archive_code] = json.load(f)
                    except Exception as e:
                        logger.error(f"加载存档 {filename} 失败: {e}")
    
    def _load_extensions(self):
        """加载扩展包"""
        global loaded_extensions
        ext_dir = "plugins/Werewolves-Master-Plugin/extensions"
        if os.path.exists(ext_dir):
            for filename in os.listdir(ext_dir):
                if filename.endswith(".json"):
                    ext_id = filename[:-5]
                    try:
                        with open(os.path.join(ext_dir, filename), 'r', encoding='utf-8') as f:
                            extension = json.load(f)
                            loaded_extensions[ext_id] = extension
                            logger.info(f"加载扩展包: {extension.get('name', ext_id)}")
                    except Exception as e:
                        logger.error(f"加载扩展包 {filename} 失败: {e}")
        else:
            # 创建默认的混乱者扩展包
            self._create_default_extension()
    
    def _create_default_extension(self):
        """创建默认扩展包"""
        default_extension = {
            "name": "混乱者包",
            "description": "包含隐狼、守卫、魔术师、双面人、通灵师、继承者、画皮、白狼王、丘比特等角色",
            "enabled": True,
            "roles": EXTENSION_ROLES
        }
        
        ext_dir = "plugins/Werewolves-Master-Plugin/extensions"
        os.makedirs(ext_dir, exist_ok=True)
        
        with open(os.path.join(ext_dir, "chaos_pack.json"), 'w', encoding='utf-8') as f:
            json.dump(default_extension, f, ensure_ascii=False, indent=2)
        
        loaded_extensions["chaos_pack"] = default_extension
        logger.info("创建默认扩展包: 混乱者包")
    
    def get_all_roles(self) -> Dict[str, Dict]:
        """获取所有角色（基础+扩展）"""
        all_roles = BASE_ROLES.copy()
        for ext_id, extension in loaded_extensions.items():
            if extension.get('enabled', True):
                for role_code, role_data in extension.get('roles', {}).items():
                    all_roles[role_code] = role_data
        return all_roles
    
    def get_role_codes_with_descriptions(self) -> str:
        """获取所有角色代码和描述"""
        all_roles = self.get_all_roles()
        result = "🎭 **可用角色列表**\n\n"
        
        result += "🏰 **基础角色**:\n"
        for code, role in BASE_ROLES.items():
            team_name = self._get_team_name(role['team'])
            result += f"🔸 {code} - {role['name']} ({team_name})\n"
        
        # 添加扩展角色
        for ext_id, extension in loaded_extensions.items():
            if extension.get('enabled', True) and extension.get('roles'):
                result += f"\n🎁 **{extension.get('name', ext_id)}**:\n"
                for code, role in extension['roles'].items():
                    team_name = self._get_team_name(role['team'])
                    result += f"🔹 {code} - {role['name']} ({team_name})\n"
        
        result += "\n💡 使用 `/wwg settings roles <角色代码> <数量>` 设置角色"
        return result
    
    def _get_team_name(self, team: str) -> str:
        """获取阵营名称"""
        return {
            'village': '村庄',
            'wolf': '狼人', 
            'third': '第三方'
        }.get(team, '未知')
    
    def save_game_file(self, room_id: str, game_data: Dict):
        """保存游戏文件"""
        file_path = f"plugins/Werewolves-Master-Plugin/games/{room_id}.json"
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(game_data, f, ensure_ascii=False, indent=2)
    
    def generate_room_id(self) -> str:
        """生成6位房间号"""
        return ''.join([str(random.randint(0, 9)) for _ in range(6)])
    
    def generate_archive_code(self) -> str:
        """生成12位存档代码"""
        import string
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
    
    def find_player_room(self, qq: str) -> Optional[str]:
        """查找玩家所在的房间"""
        for room_id, game_data in active_games.items():
            if qq in game_data['player_qqs']:
                return room_id
        return None

class MessageSender:
    """消息发送器"""
    
    @staticmethod
    async def send_private_message(qq: str, message: str):
        """发送私聊消息"""
        try:
            # 这里需要根据实际框架API进行调整
            # 假设框架提供了消息发送功能
            from src.plugin_system.apis import send_api
            success = await send_api.text_to_user(text=message, user_id=qq, platform="qq")
            if not success:
                logger.warning(f"向 {qq} 发送消息可能失败")
        except Exception as e:
            logger.error(f"发送私聊消息失败 {qq}: {e}")
    
    @staticmethod
    async def send_group_message(group_id: str, message: str):
        """发送群聊消息"""
        try:
            from src.plugin_system.apis import send_api
            success = await send_api.text_to_group(text=message, group_id=group_id, platform="qq")
            if not success:
                logger.warning(f"向群 {group_id} 发送消息可能失败")
        except Exception as e:
            logger.error(f"发送群消息失败 {group_id}: {e}")

class ActionResolver:
    """行动解析器"""
    
    def __init__(self, game_manager):
        self.gm = game_manager
    
    async def resolve_night_actions(self, game_data: Dict, room_id: str):
        """处理夜晚行动结果"""
        night_actions = game_data.get('night_actions', {})
        
        # 处理各种行动（按优先级顺序）
        await self._resolve_magician_swap(game_data, night_actions)
        kill_target = await self._resolve_wolf_kill(game_data, night_actions)
        heal_target, poison_target = await self._resolve_witch_actions(game_data, night_actions, kill_target)
        guard_target = await self._resolve_guard_action(game_data, night_actions)
        await self._resolve_seer_check(game_data, night_actions)
        await self._resolve_psychic_check(game_data, night_actions)
        await self._resolve_paint_action(game_data, night_actions)
        await self._resolve_cupid_action(game_data, night_actions)
        
        # 计算死亡目标
        final_deaths = await self._calculate_final_deaths(
            game_data, kill_target, heal_target, poison_target, guard_target
        )
        
        # 执行死亡
        await self._execute_deaths(game_data, final_deaths, room_id)
        
        # 处理继承者技能获取
        await self._resolve_inheritor_skills(game_data)
        
        # 更新隐狼状态
        await self._update_hidden_wolf_status(game_data)
        
        # 清理行动记录
        game_data['night_actions'] = {}
        if guard_target:
            game_data['last_guard_target'] = guard_target
        
        # 保存游戏状态
        self.gm.save_game_file(room_id, game_data)
    
    async def _resolve_magician_swap(self, game_data: Dict, night_actions: Dict):
        """处理魔术师交换"""
        magician_action = next((a for a in night_actions.values() 
                              if a.get('action') == 'swap'), None)
        if magician_action:
            player1 = magician_action.get('target1')
            player2 = magician_action.get('target2')
            if player1 and player2 and player1 != player2:
                game_data['magician_swap'] = (player1, player2)
                magician_qq = magician_action.get('player_qq')
                if magician_qq:
                    await MessageSender.send_private_message(
                        magician_qq, 
                        f"✅ 已交换玩家 {player1} 和 {player2} 的号码牌"
                    )
    
    async def _resolve_wolf_kill(self, game_data: Dict, night_actions: Dict) -> Optional[int]:
        """处理狼人击杀"""
        wolf_actions = [a for a in night_actions.values() 
                       if a.get('action') == 'kill' and self._is_wolf_role(a.get('role'))]
        
        # 检查隐狼是否获得刀人能力
        hidden_wolves = [p for p in game_data['players'] 
                        if p['role'] == 'HWOLF' and p['alive'] and p.get('can_kill', False)]
        for hwolf in hidden_wolves:
            hwolf_action = next((a for a in night_actions.values() 
                               if a.get('player_qq') == hwolf['qq'] and a.get('action') == 'kill'), None)
            if hwolf_action:
                wolf_actions.append(hwolf_action)
        
        if wolf_actions:
            votes = {}
            for action in wolf_actions:
                target = action.get('target')
                if target:
                    votes[target] = votes.get(target, 0) + 1
            
            if votes:
                max_votes = max(votes.values())
                candidates = [t for t, v in votes.items() if v == max_votes]
                return random.choice(candidates) if candidates else None
        
        return None
    
    async def _resolve_witch_actions(self, game_data: Dict, night_actions: Dict, kill_target: Optional[int]) -> Tuple[Optional[int], Optional[int]]:
        """处理女巫行动"""
        witch_action = next((a for a in night_actions.values() 
                           if a.get('role') == 'WITCH'), None)
        
        heal_target = None
        poison_target = None
        
        if witch_action:
            action_type = witch_action.get('action')
            target = witch_action.get('target')
            witch_qq = witch_action.get('player_qq')
            
            if action_type == 'heal' and target and game_data.get('witch_heal_available', True):
                heal_target = target
                game_data['witch_heal_available'] = False
                if witch_qq:
                    await MessageSender.send_private_message(
                        witch_qq, 
                        f"✅ 已对玩家 {target} 使用解药"
                    )
            
            elif action_type == 'poison' and target and game_data.get('witch_poison_available', True):
                poison_target = target
                game_data['witch_poison_available'] = False
                if witch_qq:
                    await MessageSender.send_private_message(
                        witch_qq, 
                        f"✅ 已对玩家 {target} 使用毒药"
                    )
            
            elif action_type == 'skip':
                if witch_qq:
                    await MessageSender.send_private_message(witch_qq, "✅ 已跳过行动")
        
        return heal_target, poison_target
    
    async def _resolve_guard_action(self, game_data: Dict, night_actions: Dict) -> Optional[int]:
        """处理守卫守护"""
        guard_action = next((a for a in night_actions.values() 
                           if a.get('role') == 'GUARD'), None)
        
        if guard_action and guard_action.get('action') == 'guard':
            target = guard_action.get('target')
            guard_qq = guard_action.get('player_qq')
            last_guard = game_data.get('last_guard_target')
            
            if target != last_guard:
                if guard_qq:
                    await MessageSender.send_private_message(
                        guard_qq, 
                        f"✅ 已守护玩家 {target}"
                    )
                return target
            else:
                if guard_qq:
                    await MessageSender.send_private_message(
                        guard_qq, 
                        "❌ 不能连续两晚守护同一名玩家"
                    )
        
        return None
    
    async def _resolve_seer_check(self, game_data: Dict, night_actions: Dict):
        """处理预言家查验"""
        seer_action = next((a for a in night_actions.values() 
                          if a.get('role') == 'SEER'), None)
        
        if seer_action and seer_action.get('action') == 'check':
            target_num = seer_action.get('target')
            seer_qq = seer_action.get('player_qq')
            
            if target_num and seer_qq:
                target_player = self._get_player_by_number(game_data, target_num)
                if target_player and target_player['alive']:
                    # 处理隐狼和画皮的特殊情况
                    actual_role = target_player['role']
                    display_role = actual_role
                    
                    # 画皮伪装
                    if (game_data.get('paint_disguise') and 
                        game_data['paint_disguise'].get('painter_qq') == target_player['qq']):
                        display_role = game_data['paint_disguise']['disguised_role']
                    
                    # 隐狼显示为好人
                    if display_role == 'HWOLF':
                        display_team = 'village'
                    else:
                        display_team = self.gm.get_all_roles()[display_role]['team']
                    
                    result_msg = f"玩家 {target_num} 的阵营是: {self._get_team_name(display_team)}"
                    await MessageSender.send_private_message(seer_qq, result_msg)
    
    async def _resolve_psychic_check(self, game_data: Dict, night_actions: Dict):
        """处理通灵师查验"""
        psychic_action = next((a for a in night_actions.values() 
                             if a.get('role') == 'PSYC'), None)
        
        if psychic_action and psychic_action.get('action') == 'check':
            target_num = psychic_action.get('target')
            psychic_qq = psychic_action.get('player_qq')
            
            if target_num and psychic_qq:
                target_player = self._get_player_by_number(game_data, target_num)
                if target_player and target_player['alive']:
                    # 通灵师能看到真实身份（包括画皮伪装）
                    actual_role = target_player['role']
                    if (game_data.get('paint_disguise') and 
                        game_data['paint_disguise'].get('painter_qq') == target_player['qq']):
                        actual_role = game_data['paint_disguise']['disguised_role']
                    
                    role_name = self.gm.get_all_roles()[actual_role]['name']
                    result_msg = f"玩家 {target_num} 的身份是: {role_name}"
                    await MessageSender.send_private_message(psychic_qq, result_msg)
    
    async def _resolve_paint_action(self, game_data: Dict, night_actions: Dict):
        """处理画皮伪装"""
        paint_action = next((a for a in night_actions.values() 
                           if a.get('role') == 'PAINT'), None)
        
        if paint_action and paint_action.get('action') == 'paint':
            target_num = paint_action.get('target')
            paint_qq = paint_action.get('player_qq')
            
            if target_num and paint_qq:
                target_player = self._get_dead_player_by_number(game_data, target_num)
                if target_player:
                    game_data['paint_disguise'] = {
                        'painter_qq': paint_qq,
                        'disguised_role': target_player['role']
                    }
                    role_name = self.gm.get_all_roles()[target_player['role']]['name']
                    await MessageSender.send_private_message(
                        paint_qq, 
                        f"✅ 已伪装成玩家 {target_num} 的身份: {role_name}"
                    )
    
    async def _resolve_cupid_action(self, game_data: Dict, night_actions: Dict):
        """处理丘比特行动"""
        cupid_action = next((a for a in night_actions.values() 
                           if a.get('role') == 'CUPID'), None)
        
        if cupid_action and cupid_action.get('action') == 'connect':
            target1 = cupid_action.get('target1')
            target2 = cupid_action.get('target2')
            cupid_qq = cupid_action.get('player_qq')
            
            if target1 and target2 and target1 != target2:
                player1 = self._get_player_by_number(game_data, target1)
                player2 = self._get_player_by_number(game_data, target2)
                
                if player1 and player2:
                    game_data['lovers'] = [target1, target2]
                    game_data['cupid'] = cupid_qq
                    
                    # 通知情侣
                    lover_msg = "💕 你被丘比特选中成为情侣！如果情侣死亡，你也会殉情。"
                    await MessageSender.send_private_message(player1['qq'], lover_msg)
                    await MessageSender.send_private_message(player2['qq'], lover_msg)
                    
                    await MessageSender.send_private_message(
                        cupid_qq, 
                        f"✅ 已连接玩家 {target1} 和 {target2} 成为情侣"
                    )
    
    async def _calculate_final_deaths(self, game_data: Dict, kill_target: Optional[int], 
                                    heal_target: Optional[int], poison_target: Optional[int], 
                                    guard_target: Optional[int]) -> Set[int]:
        """计算最终死亡目标"""
        deaths = set()
        
        # 狼人击杀
        if kill_target and kill_target != heal_target and kill_target != guard_target:
            killed_player = self._get_player_by_number(game_data, kill_target)
            if killed_player:
                # 检查双面人特殊效果
                if killed_player['role'] == 'DUAL':
                    killed_player['team'] = 'wolf'
                    killed_player['role'] = 'WOLF'
                    await self._notify_team_change(game_data, killed_player, 'wolf')
                else:
                    deaths.add(kill_target)
        
        # 女巫毒药（双面人免疫）
        if poison_target:
            poisoned_player = self._get_player_by_number(game_data, poison_target)
            if poisoned_player and poisoned_player['role'] != 'DUAL':
                deaths.add(poison_target)
                poisoned_player['death_reason'] = 'poisoned'
        
        # 处理情侣殉情
        lovers = game_data.get('lovers', [])
        for death in list(deaths):
            if death in lovers:
                # 找到另一个情侣
                other_lover = next((l for l in lovers if l != death), None)
                if other_lover:
                    other_player = self._get_player_by_number(game_data, other_lover)
                    if other_player and other_player['alive']:
                        deaths.add(other_lover)
                        # 记录殉情
                        other_player['death_reason'] = 'lover_suicide'
        
        return deaths
    
    async def _execute_deaths(self, game_data: Dict, deaths: Set[int], room_id: str):
        """执行死亡"""
        death_messages = []
        
        for death_num in deaths:
            player = self._get_player_by_number(game_data, death_num)
            if player and player['alive']:
                player['alive'] = False
                player['death_time'] = time.time()
                
                # 检查猎人技能（非毒杀）
                if player['role'] == 'HUNT' and player.get('death_reason') != 'poisoned':
                    game_data['hunter_revenge'] = player['qq']
                    await MessageSender.send_private_message(
                        player['qq'], 
                        "🔫 你已死亡，可以使用 `/wwg shoot <玩家号>` 开枪复仇"
                    )
                
                death_reason = player.get('death_reason', 'killed')
                if death_reason == 'lover_suicide':
                    death_messages.append(f"玩家 {death_num} 殉情死亡")
                elif death_reason == 'poisoned':
                    death_messages.append(f"玩家 {death_num} 被毒杀")
                else:
                    death_messages.append(f"玩家 {death_num} 死亡")
        
        if death_messages:
            death_msg = "🌙 **夜晚结算**\n" + "\n".join(death_messages)
            await self._broadcast_to_players(game_data, death_msg)
    
    async def _resolve_inheritor_skills(self, game_data: Dict):
        """处理继承者技能获取"""
        for player in game_data['players']:
            if player['role'] == 'INHE' and player['alive'] and not player.get('inherited'):
                adjacent_nums = [player['number'] - 1, player['number'] + 1]
                dead_gods = []
                
                for adj_num in adjacent_nums:
                    adj_player = self._get_player_by_number(game_data, adj_num)
                    if (adj_player and not adj_player['alive'] and 
                        self.gm.get_all_roles()[adj_player['role']]['team'] == 'village' and
                        adj_player['role'] not in ['VILL', 'INHE']):
                        dead_gods.append(adj_player)
                
                if dead_gods:
                    first_dead = min(dead_gods, key=lambda p: p.get('death_time', float('inf')))
                    player['inherited_role'] = first_dead['role']
                    player['inherited'] = True
                    
                    skill_msg = f"🎁 你继承了玩家 {first_dead['number']} 的 {self.gm.get_all_roles()[first_dead['role']]['name']} 技能"
                    await MessageSender.send_private_message(player['qq'], skill_msg)
    
    async def _update_hidden_wolf_status(self, game_data: Dict):
        """更新隐狼状态"""
        # 检查是否还有其他狼人存活
        alive_wolves = [p for p in game_data['players'] 
                       if p['alive'] and p['role'] != 'HWOLF' and self._is_wolf_role(p['role'])]
        
        for player in game_data['players']:
            if player['role'] == 'HWOLF' and player['alive']:
                if not alive_wolves and not player.get('can_kill', False):
                    # 其他狼人都死了，隐狼获得刀人能力
                    player['can_kill'] = True
                    await MessageSender.send_private_message(
                        player['qq'], 
                        "🐺 所有狼人队友已出局，你获得了刀人能力！"
                    )
    
    async def _notify_team_change(self, game_data: Dict, player: Dict, new_team: str):
        """通知阵营变化"""
        team_name = self._get_team_name(new_team)
        msg = f"🔄 你的阵营已转变为: {team_name}"
        await MessageSender.send_private_message(player['qq'], msg)
    
    def _is_wolf_role(self, role: str) -> bool:
        """检查是否为狼人阵营角色"""
        all_roles = self.gm.get_all_roles()
        return role in all_roles and all_roles[role]['team'] == 'wolf'
    
    def _get_player_by_number(self, game_data: Dict, number: int) -> Optional[Dict]:
        """根据玩家号获取玩家"""
        return next((p for p in game_data['players'] if p['number'] == number), None)
    
    def _get_dead_player_by_number(self, game_data: Dict, number: int) -> Optional[Dict]:
        """根据玩家号获取死亡玩家"""
        player = self._get_player_by_number(game_data, number)
        return player if player and not player['alive'] else None
    
    def _get_team_name(self, team: str) -> str:
        """获取阵营名称"""
        return {
            'village': '村庄阵营',
            'wolf': '狼人阵营',
            'third': '第三方阵营'
        }.get(team, '未知阵营')
    
    async def _broadcast_to_players(self, game_data: Dict, message: str):
        """向所有玩家广播消息"""
        for player in game_data['players']:
            await MessageSender.send_private_message(player['qq'], message)

class GamePhaseManager:
    """游戏阶段管理器"""
    
    def __init__(self, game_manager, action_resolver):
        self.gm = game_manager
        self.resolver = action_resolver
    
    async def start_game(self, game_data: Dict, room_id: str):
        """开始游戏"""
        await self._assign_roles(game_data, room_id)
        await self._notify_players(game_data)
        await self._start_night_phase(game_data, room_id)
    
    async def _assign_roles(self, game_data: Dict, room_id: str):
        """分配角色给玩家"""
        players = game_data['players']
        role_settings = game_data['settings']['roles']
        all_roles = self.gm.get_all_roles()
        
        # 生成角色列表
        role_list = []
        for role_code, count in role_settings.items():
            if role_code in all_roles:
                role_list.extend([role_code] * count)
        
        # 检查角色数量是否匹配
        if len(role_list) != len(players):
            # 自动调整角色数量
            needed_roles = len(players) - len(role_list)
            if needed_roles > 0:
                # 添加村民
                role_list.extend(['VILL'] * needed_roles)
            else:
                # 移除多余角色
                role_list = role_list[:len(players)]
        
        # 随机分配
        random.shuffle(players)
        random.shuffle(role_list)
        
        for i, player in enumerate(players):
            if i < len(role_list):
                player['role'] = role_list[i]
                player['alive'] = True
                player['vote'] = None
        
        # 初始化特殊状态
        game_data['witch_heal_available'] = True
        game_data['witch_poison_available'] = True
        game_data['night_actions'] = {}
        game_data['night_count'] = 0
        game_data['game_started'] = True
        
        self.gm.save_game_file(room_id, game_data)
    
    async def _notify_players(self, game_data: Dict):
        """通知所有玩家他们的角色"""
        all_roles = self.gm.get_all_roles()
        
        for player in game_data['players']:
            role_code = player['role']
            if role_code in all_roles:
                role_info = all_roles[role_code]
                role_name = role_info['name']
                team = role_info['team']
                
                message = (
                    f"🎭 **游戏开始！你的身份是: {role_name}**\n\n"
                    f"🏷️ 阵营: {self._get_team_name(team)}\n"
                    f"🔢 玩家号: {player['number']}\n"
                    f"📝 描述: {role_info['description']}\n"
                )
                
                # 添加角色特定说明
                if role_code == "SEER":
                    message += "\n🔮 夜晚使用 `/wwg check <玩家号>` 查验身份"
                elif role_code == "WITCH":
                    message += "\n🧪 夜晚使用 `/wwg heal <玩家号>` 救人或 `/wwg poison <玩家号>` 毒人"
                elif role_code == "WOLF":
                    message += "\n🐺 夜晚使用 `/wwg kill <玩家号>` 选择击杀目标"
                elif role_code == "HUNT":
                    message += "\n🔫 死亡时使用 `/wwg shoot <玩家号>` 开枪复仇"
                elif role_code == "GUARD":
                    message += "\n🛡️ 夜晚使用 `/wwg guard <玩家号>` 守护玩家"
                elif role_code == "PSYC":
                    message += "\n🔍 夜晚使用 `/wwg psychic <玩家号>` 查验具体身份"
                elif role_code == "MAGI":
                    message += "\n🎭 夜晚使用 `/wwg swap <玩家号1> <玩家号2>` 交换号码牌"
                elif role_code == "PAINT":
                    message += "\n🎨 第二夜起使用 `/wwg paint <死亡玩家号>` 伪装身份"
                elif role_code == "WWOLF":
                    message += "\n💥 白天使用 `/wwg explode <玩家号>` 自爆并带走玩家"
                elif role_code == "CUPID":
                    message += "\n💕 第一夜使用 `/wwg connect <玩家号1> <玩家号2>` 连接情侣"
                elif role_code == "HWOLF":
                    message += "\n🐺 隐狼：被查验显示为好人，其他狼人出局后获得刀人能力"
                elif role_code == "DUAL":
                    message += "\n🔄 双面人：被狼杀加入狼人，被投票加入好人，免疫毒药"
                elif role_code == "INHE":
                    message += "\n🎁 继承者：相邻神民死亡时继承其技能"
                
                message += "\n\n💡 使用 `/wwg skip` 跳过夜晚行动"
                
                await MessageSender.send_private_message(player['qq'], message)
        
        # 通知所有玩家游戏开始
        start_msg = (
            f"🎮 **游戏开始！**\n\n"
            f"👥 玩家总数: {len(game_data['players'])}\n"
            f"🌙 第一夜开始，请有能力的玩家行动\n"
            f"⏰ 行动时间: {self.gm.plugin.get_config('game.default_night_time', 300)//60} 分钟"
        )
        await self.resolver._broadcast_to_players(game_data, start_msg)
    
    async def _start_night_phase(self, game_data: Dict, room_id: str):
        """开始夜晚流程"""
        game_data['phase'] = 'night'
        game_data['night_count'] = game_data.get('night_count', 0) + 1
        game_data['last_activity'] = time.time()
        self.gm.save_game_file(room_id, game_data)
        
        asyncio.create_task(self._night_phase(game_data, room_id))
    
    async def _night_phase(self, game_data: Dict, room_id: str):
        """夜晚流程"""
        night_time = self.gm.plugin.get_config("game.default_night_time", 300)
        
        # 通知所有玩家夜晚开始
        night_msg = (
            f"🌙 **第{game_data['night_count']}夜开始**\n"
            f"请有能力的玩家在 {night_time//60} 分钟内行动\n"
            f"使用 `/wwg skip` 跳过行动"
        )
        await self.resolver._broadcast_to_players(game_data, night_msg)
        
        # 等待夜晚结束
        await asyncio.sleep(night_time)
        
        # 处理夜晚行动结果
        await self.resolver.resolve_night_actions(game_data, room_id)
        
        # 检查游戏是否结束
        if await self._check_game_end(game_data, room_id):
            return
        
        # 进入白天
        await self._start_day_phase(game_data, room_id)
    
    async def _start_day_phase(self, game_data: Dict, room_id: str):
        """开始白天流程"""
        game_data['phase'] = 'day'
        game_data['last_activity'] = time.time()
        self.gm.save_game_file(room_id, game_data)
        
        asyncio.create_task(self._day_phase(game_data, room_id))
    
    async def _day_phase(self, game_data: Dict, room_id: str):
        """白天流程"""
        day_time = self.gm.plugin.get_config("game.default_day_time", 300)
        alive_players = [p for p in game_data['players'] if p['alive']]
        
        # 通知所有玩家白天开始
        day_msg = (
            f"☀️ **白天开始**\n\n"
            f"👥 存活玩家: {len(alive_players)}\n"
            f"⏰ 请在 {day_time//60} 分钟内进行讨论和投票\n"
            f"🗳️ 使用 `/wwg vote <玩家号>` 投票\n"
            f"💥 白狼王可使用 `/wwg explode <玩家号>` 自爆"
        )
        await self.resolver._broadcast_to_players(game_data, day_msg)
        
        # 等待白天结束
        await asyncio.sleep(day_time)
        
        # 处理投票结果
        await self._resolve_voting(game_data, room_id)
        
        # 检查游戏是否结束
        if await self._check_game_end(game_data, room_id):
            return
        
        # 进入下一夜
        await self._start_night_phase(game_data, room_id)
    
    async def _resolve_voting(self, game_data: Dict, room_id: str):
        """处理投票结果"""
        votes = {}
        voted_players = []
        
        for player in game_data['players']:
            if player['alive'] and player['vote']:
                vote_target = player['vote']
                votes[vote_target] = votes.get(vote_target, 0) + 1
                voted_players.append(player['number'])
        
        if votes:
            max_votes = max(votes.values())
            candidates = [target for target, count in votes.items() if count == max_votes]
            
            if len(candidates) == 1:
                executed_number = candidates[0]
                executed_player = self.resolver._get_player_by_number(game_data, executed_number)
                
                if executed_player:
                    # 检查双面人特殊效果
                    if executed_player['role'] == 'DUAL':
                        executed_player['team'] = 'village'
                        await self.resolver._notify_team_change(game_data, executed_player, 'village')
                        # 双面人被投票不死亡
                        vote_msg = f"⚖️ 玩家 {executed_number} 被投票，阵营转变为村庄"
                    else:
                        executed_player['alive'] = False
                        executed_player['death_reason'] = 'voted'
                        executed_player['death_time'] = time.time()
                        vote_msg = f"⚖️ 玩家 {executed_number} 被投票处决"
                    
                    await self.resolver._broadcast_to_players(game_data, vote_msg)
            
            else:
                # 平票，无人死亡
                tied_players = ", ".join(map(str, candidates))
                await self.resolver._broadcast_to_players(
                    game_data, 
                    f"⚖️ 投票平票 ({tied_players})，无人被处决"
                )
        
        else:
            await self.resolver._broadcast_to_players(game_data, "⚖️ 无人投票，无人被处决")
        
        # 重置所有玩家的投票
        for player in game_data['players']:
            player['vote'] = None
        
        self.gm.save_game_file(room_id, game_data)
    
    async def _check_game_end(self, game_data: Dict, room_id: str) -> bool:
        """检查游戏是否结束"""
        alive_players = [p for p in game_data['players'] if p['alive']]
        all_roles = self.gm.get_all_roles()
        
        if len(alive_players) == 0:
            # 无人存活，平局
            await self._end_game(game_data, room_id, 'draw')
            return True
        
        # 统计各阵营存活人数
        village_count = 0
        wolf_count = 0
        third_count = 0
        
        for player in alive_players:
            role_info = all_roles[player['role']]
            if role_info['team'] == 'village':
                village_count += 1
            elif role_info['team'] == 'wolf':
                wolf_count += 1
            elif role_info['team'] == 'third':
                third_count += 1
        
        # 检查情侣阵营胜利
        lovers = game_data.get('lovers', [])
        if lovers:
            lovers_alive = all(self.resolver._get_player_by_number(game_data, l) and 
                             self.resolver._get_player_by_number(game_data, l)['alive'] 
                             for l in lovers)
            cupid_alive = (game_data.get('cupid') and 
                          any(p['qq'] == game_data['cupid'] and p['alive'] for p in alive_players))
            
            if lovers_alive and cupid_alive and len(alive_players) == 3:
                await self._end_game(game_data, room_id, 'lovers')
                return True
        
        # 检查基础胜利条件
        winner = None
        if wolf_count == 0 and third_count == 0:
            winner = 'village'
        elif wolf_count >= village_count + third_count:
            winner = 'wolf'
        
        if winner:
            await self._end_game(game_data, room_id, winner)
            return True
        
        return False
    
    async def _end_game(self, game_data: Dict, room_id: str, winner: str):
        """结束游戏"""
        game_data['ended'] = True
        game_data['end_time'] = datetime.now().isoformat()
        game_data['winner'] = winner
        
        # 生成存档代码
        archive_code = self.gm.generate_archive_code()
        game_archives[archive_code] = game_data.copy()
        
        # 保存到完成的对局文件夹
        archive_path = f"plugins/Werewolves-Master-Plugin/games/finished/{archive_code}.json"
        with open(archive_path, 'w', encoding='utf-8') as f:
            json.dump(game_data, f, ensure_ascii=False, indent=2)
        
        # 更新玩家档案
        await self._update_profiles(game_data, winner)
        
        # 发送游戏结果
        winner_name = self._get_winner_name(winner)
        result_msg = (
            f"🎉 **游戏结束！**\n\n"
            f"🏆 胜利方: {winner_name}\n"
            f"📊 对局码: `{archive_code}`\n\n"
            f"👥 **玩家身份**:\n"
        )
        
        all_roles = self.gm.get_all_roles()
        for player in game_data['players']:
            role_name = all_roles[player['role']]['name']
            status = "✅ 存活" if player['alive'] else "❌ 死亡"
            death_reason = f" ({player.get('death_reason')})" if not player['alive'] else ""
            result_msg += f"玩家 {player['number']}: {role_name} - {status}{death_reason}\n"
        
        await self.resolver._broadcast_to_players(game_data, result_msg)
        
        # 从活跃游戏中移除
        if room_id in active_games:
            del active_games[room_id]
        
        # 删除临时游戏文件
        temp_file = f"plugins/Werewolves-Master-Plugin/games/{room_id}.json"
        if os.path.exists(temp_file):
            os.remove(temp_file)
    
    async def _update_profiles(self, game_data: Dict, winner: str):
        """更新玩家档案"""
        all_roles = self.gm.get_all_roles()
        
        for player in game_data['players']:
            qq = player['qq']
            if qq not in player_profiles:
                player_profiles[qq] = {
                    'games_played': 0,
                    'games_won': 0,
                    'games_lost': 0,
                    'kills': 0,
                    'votes': 0,
                    'recent_win_rate': []
                }
            
            profile = player_profiles[qq]
            profile['games_played'] += 1
            
            # 判断胜负
            is_winner = False
            if winner == 'draw':
                # 平局不计胜负
                pass
            elif winner == 'lovers':
                # 情侣阵营胜利
                is_winner = (player['qq'] == game_data.get('cupid') or 
                           any(player['number'] == l for l in game_data.get('lovers', [])))
            else:
                # 基础阵营胜利
                player_team = all_roles[player['role']]['team']
                is_winner = (player_team == winner)
            
            if is_winner:
                profile['games_won'] += 1
                profile['recent_win_rate'].append(1)
            else:
                profile['games_lost'] += 1
                profile['recent_win_rate'].append(0)
            
            # 统计击杀和票杀
            if player.get('death_reason') == 'shot':
                # 找到开枪的猎人
                for p in game_data['players']:
                    if p.get('death_reason') == 'killed' and p.get('killer') == player['qq']:
                        profile['kills'] = profile.get('kills', 0) + 1
                        break
            
            if player.get('death_reason') == 'voted':
                # 统计投票数
                vote_count = sum(1 for p in game_data['players'] 
                               if p.get('vote') == player['number'])
                profile['votes'] = profile.get('votes', 0) + vote_count
            
            # 保持最近10场记录
            if len(profile['recent_win_rate']) > 10:
                profile['recent_win_rate'] = profile['recent_win_rate'][-10:]
            
            # 保存档案
            profile_path = f"plugins/Werewolves-Master-Plugin/users/{qq}.json"
            with open(profile_path, 'w', encoding='utf-8') as f:
                json.dump(profile, f, ensure_ascii=False, indent=2)
    
    def _get_team_name(self, team: str) -> str:
        """获取阵营名称"""
        return {
            'village': '村庄阵营',
            'wolf': '狼人阵营',
            'third': '第三方阵营'
        }.get(team, '未知阵营')
    
    def _get_winner_name(self, winner: str) -> str:
        """获取胜利方名称"""
        return {
            'village': '🏰 村庄阵营',
            'wolf': '🐺 狼人阵营', 
            'lovers': '💕 情侣阵营',
            'draw': '🤝 平局'
        }.get(winner, '未知阵营')

# ================= 主插件类 =================
class WerewolfGamePlugin(BasePlugin):
    """狼人杀游戏插件"""
    
    plugin_name = "werewolf_game"
    enable_plugin = True
    dependencies = []
    python_dependencies = []
    config_file_name = "werewolf_config.toml"
    
    config_section_descriptions = {
        "plugin": "插件基础配置",
        "game": "游戏设置",
        "timing": "时间控制"
    }
    
    config_schema = {
        "plugin": {
            "enabled": ConfigField(type=bool, default=True, description="是否启用插件"),
            "config_version": ConfigField(type=str, default="1.0.0", description="配置文件版本"),
        },
        "game": {
            "max_players": ConfigField(type=int, default=18, description="最大玩家数"),
            "min_players": ConfigField(type=int, default=6, description="最小玩家数"),
            "default_night_time": ConfigField(type=int, default=300, description="默认夜晚时间(秒)"),
            "default_day_time": ConfigField(type=int, default=300, description="默认白天时间(秒)"),
        },
        "timing": {
            "room_timeout": ConfigField(type=int, default=1200, description="房间超时时间(秒)"),
            "game_timeout": ConfigField(type=int, default=1800, description="游戏中超时时间(秒)"),
        }
    }
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.gm = GameManager(self)
        self.resolver = ActionResolver(self.gm)
        self.phase_manager = GamePhaseManager(self.gm, self.resolver)
        self._cleanup_task = asyncio.create_task(self._cleanup_inactive_rooms())
    
    async def _cleanup_inactive_rooms(self):
        """清理不活跃的房间"""
        while True:
            await asyncio.sleep(60)
            current_time = time.time()
            rooms_to_remove = []
            
            for room_id, game_data in active_games.items():
                last_activity = game_data.get('last_activity', 0)
                timeout = self.get_config("timing.room_timeout", 1200)
                if game_data.get('game_started', False):
                    timeout = self.get_config("timing.game_timeout", 1800)
                
                if current_time - last_activity > timeout:
                    rooms_to_remove.append(room_id)
            
            for room_id in rooms_to_remove:
                if room_id in active_games:
                    game_data = active_games[room_id]
                    close_msg = "⏰ 房间因长时间无活动已关闭"
                    await self.resolver._broadcast_to_players(game_data, close_msg)
                    del active_games[room_id]
                    
                    temp_file = f"plugins/Werewolves-Master-Plugin/games/{room_id}.json"
                    if os.path.exists(temp_file):
                        os.remove(temp_file)

# ================= 命令基类 =================
class WWGBaseCommand(BaseCommand):
    """狼人杀命令基类"""
    
    intercept_message = True
    
    def _get_sender_qq(self) -> Optional[str]:
        """获取发送者QQ号"""
        try:
            message_obj = getattr(self, 'message', None)
            if not message_obj:
                return None
            
            # 尝试多种可能的字段路径
            sender_paths = [
                "message_info.user_info.user_id",
                "sender.user_id", 
                "user_id",
                "ctx.user_id",
                "sender_qq"
            ]
            
            for path in sender_paths:
                parts = path.split('.')
                obj = message_obj
                for part in parts:
                    if hasattr(obj, part):
                        obj = getattr(obj, part)
                    elif isinstance(obj, dict) and part in obj:
                        obj = obj[part]
                    else:
                        obj = None
                        break
                if obj:
                    return str(obj)
            
            return None
        except Exception as e:
            logger.error(f"获取发送者QQ失败: {e}")
            return None

class WWGNightActionCommand(WWGBaseCommand):
    """夜晚行动基类"""
    
    async def _check_night_action_prerequisites(self, sender_qq: str) -> Tuple[bool, Optional[str], Optional[Dict], Optional[Dict]]:
        """检查夜晚行动前提条件"""
        plugin = getattr(self, 'plugin', None)
        if not plugin:
            return False, "❌ 插件未正确初始化", None, None
        
        room_id = plugin.gm.find_player_room(sender_qq)
        if not room_id:
            return False, "❌ 你不在任何游戏房间中", None, None
        
        game_data = active_games[room_id]
        
        if game_data['phase'] != 'night':
            return False, "❌ 现在不是夜晚行动时间", None, None
        
        sender_player = next((p for p in game_data['players'] if p['qq'] == sender_qq), None)
        if not sender_player or not sender_player['alive']:
            return False, "❌ 死亡玩家不能行动", None, None
        
        all_roles = plugin.gm.get_all_roles()
        role_info = all_roles.get(sender_player['role'], {})
        
        if not role_info.get('night_action', False):
            return False, "❌ 你的角色没有夜晚行动能力", None, None
        
        return True, None, game_data, sender_player

# ================= 游戏管理命令 =================
class WWGHelpCommand(WWGBaseCommand):
    """狼人杀帮助命令"""
    
    command_name = "wwg_help"
    command_description = "显示狼人杀游戏帮助"
    command_pattern = r"^/wwg$"
    
    async def execute(self) -> Tuple[bool, str, bool]:
        help_text = (
            "🐺 **狼人杀游戏帮助** 🐺\n\n"
            "🎮 **游戏命令**:\n"
            "🔸 `/wwg host` - 创建房间\n"
            "🔸 `/wwg join <房间号>` - 加入房间\n"
            "🔸 `/wwg start` - 开始游戏\n"
            "🔸 `/wwg settings players <数量>` - 设置玩家数\n"
            "🔸 `/wwg settings roles <角色> <数量>` - 设置角色数量\n"
            "🔸 `/wwg settings extends <扩展ID> <true/false>` - 启用/禁用扩展\n"
            "🔸 `/wwg vote <玩家号>` - 投票\n"
            "🔸 `/wwg skip` - 跳过行动\n"
            "🔸 `/wwg profile [QQ号]` - 查看档案\n"
            "🔸 `/wwg archive <对局码>` - 查询对局记录\n"
            "🔸 `/wwg roles` - 查看可用角色代码\n\n"
            "🌙 **夜晚行动命令**:\n"
            "🔹 预言家: `/wwg check <玩家号>`\n"
            "🔹 女巫: `/wwg heal <玩家号>` / `/wwg poison <玩家号>`\n"
            "🔹 狼人: `/wwg kill <玩家号>`\n"
            "🔹 守卫: `/wwg guard <玩家号>`\n"
            "🔹 通灵师: `/wwg psychic <玩家号>`\n"
            "🔹 魔术师: `/wwg swap <玩家号1> <玩家号2>`\n"
            "🔹 画皮: `/wwg paint <死亡玩家号>`\n"
            "🔹 丘比特: `/wwg connect <玩家号1> <玩家号2>`\n\n"
            "☀️ **白天行动命令**:\n"
            "🔹 猎人: `/wwg shoot <玩家号>`\n"
            "🔹 白狼王: `/wwg explode <玩家号>`\n\n"
            "💡 使用具体命令查看详细说明"
        )
        await self.send_text(help_text)
        return True, "help_sent", True

class WWGRolesCommand(WWGBaseCommand):
    """查看角色代码命令"""
    
    command_name = "wwg_roles"
    command_description = "查看所有可用角色代码"
    command_pattern = r"^/wwg roles$"
    
    async def execute(self) -> Tuple[bool, str, bool]:
        plugin = getattr(self, 'plugin', None)
        if plugin and hasattr(plugin, 'gm'):
            roles_text = plugin.gm.get_role_codes_with_descriptions()
            await self.send_text(roles_text)
            return True, "roles_shown", True
        else:
            await self.send_text("❌ 无法获取角色列表")
            return False, "plugin_error", True

class WWGHostCommand(WWGBaseCommand):
    """创建房间命令"""
    
    command_name = "wwg_host"
    command_description = "创建狼人杀房间"
    command_pattern = r"^/wwg host$"
    
    async def execute(self) -> Tuple[bool, str, bool]:
        sender_qq = self._get_sender_qq()
        if not sender_qq:
            await self.send_text("❌ 无法获取用户信息")
            return False, "no_sender_info", True
        
        plugin = getattr(self, 'plugin', None)
        if not plugin:
            await self.send_text("❌ 插件未正确初始化")
            return False, "plugin_error", True
        
        room_id = plugin.gm.generate_room_id()
        
        game_data = {
            'room_id': room_id,
            'host': sender_qq,
            'players': [{
                'qq': sender_qq,
                'number': 1,
                'role': None,
                'alive': True,
                'vote': None
            }],
            'player_qqs': [sender_qq],
            'player_numbers': {'1': sender_qq},
            'settings': {
                'player_count': 8,
                'roles': {'VILL': 3, 'SEER': 1, 'WITCH': 1, 'HUNT': 1, 'WOLF': 2},
                'extends': {}
            },
            'game_started': False,
            'phase': 'waiting',
            'created_time': datetime.now().isoformat(),
            'last_activity': time.time(),
            'night_actions': {},
            'witch_heal_available': True,
            'witch_poison_available': True
        }
        
        active_games[room_id] = game_data
        plugin.gm.save_game_file(room_id, game_data)
        
        response = (
            f"🎮 **狼人杀房间创建成功**\n\n"
            f"🏠 房间号: `{room_id}`\n"
            f"👑 房主: {sender_qq}\n"
            f"👥 当前玩家: 1/8\n"
            f"⏰ 房间有效期: 20分钟\n\n"
            f"其他玩家使用: `/wwg join {room_id}` 加入游戏"
        )
        
        await self.send_text(response)
        return True, f"room_created:{room_id}", True

class WWGJoinCommand(WWGBaseCommand):
    """加入房间命令"""
    
    command_name = "wwg_join"
    command_description = "加入狼人杀房间"
    command_pattern = r"^/wwg join\s+(?P<room_id>\d+)$"
    
    async def execute(self) -> Tuple[bool, str, bool]:
        room_id = self.matched_groups.get("room_id", "").strip()
        sender_qq = self._get_sender_qq()
        
        if not room_id or not sender_qq:
            await self.send_text("❌ 参数错误")
            return False, "invalid_params", True
        
        if room_id not in active_games:
            await self.send_text("❌ 房间不存在或已过期")
            return False, "room_not_found", True
        
        game_data = active_games[room_id]
        
        if sender_qq in game_data['player_qqs']:
            await self.send_text("❌ 你已经在房间中了")
            return False, "already_joined", True
        
        max_players = game_data['settings']['player_count']
        if len(game_data['players']) >= max_players:
            await self.send_text("❌ 房间已满")
            return False, "room_full", True
        
        if game_data['game_started']:
            await self.send_text("❌ 游戏已开始，无法加入")
            return False, "game_started", True
        
        player_number = len(game_data['players']) + 1
        game_data['players'].append({
            'qq': sender_qq,
            'number': player_number,
            'role': None,
            'alive': True,
            'vote': None
        })
        game_data['player_qqs'].append(sender_qq)
        game_data['player_numbers'][str(player_number)] = sender_qq
        game_data['last_activity'] = time.time()
        
        plugin = getattr(self, 'plugin', None)
        if plugin:
            plugin.gm.save_game_file(room_id, game_data)
        
        response = (
            f"✅ **加入房间成功**\n\n"
            f"🏠 房间号: `{room_id}`\n"
            f"🎯 你的玩家号: {player_number}\n"
            f"👥 当前玩家: {len(game_data['players'])}/{max_players}\n\n"
            f"等待房主开始游戏..."
        )
        
        await self.send_text(response)
        
        # 通知房主
        host_qq = game_data['host']
        if host_qq != sender_qq:
            host_msg = f"玩家 {sender_qq} 已加入房间，当前玩家数: {len(game_data['players'])}/{max_players}"
            await MessageSender.send_private_message(host_qq, host_msg)
        
        return True, f"joined_room:{room_id}", True

class WWGSettingsCommand(WWGBaseCommand):
    """房间设置命令"""
    
    command_name = "wwg_settings"
    command_description = "修改房间设置"
    command_pattern = r"^/wwg settings\s+(?P<setting_type>\w+)(?:\s+(?P<params>.+))?$"
    
    async def execute(self) -> Tuple[bool, str, bool]:
        sender_qq = self._get_sender_qq()
        setting_type = self.matched_groups.get("setting_type", "").lower()
        params = self.matched_groups.get("params", "").strip()
        
        plugin = getattr(self, 'plugin', None)
        if not plugin:
            await self.send_text("❌ 插件未正确初始化")
            return False, "plugin_error", True
        
        room_id = plugin.gm.find_player_room(sender_qq)
        if not room_id:
            await self.send_text("❌ 你不在任何房间中")
            return False, "not_in_room", True
        
        game_data = active_games[room_id]
        
        if game_data['host'] != sender_qq:
            await self.send_text("❌ 只有房主可以修改设置")
            return False, "not_host", True
        
        if game_data['game_started']:
            await self.send_text("❌ 游戏已开始，无法修改设置")
            return False, "game_started", True
        
        if setting_type == "players":
            await self._set_players(game_data, room_id, params, plugin)
        elif setting_type == "roles":
            await self._set_roles(game_data, room_id, params, plugin)
        elif setting_type == "extends":
            await self._set_extends(game_data, room_id, params, plugin)
        else:
            await self.send_text("❌ 未知的设置类型")
            return False, "unknown_setting", True
        
        return True, "settings_updated", True
    
    async def _set_players(self, game_data: Dict, room_id: str, params: str, plugin):
        """设置玩家数量"""
        try:
            player_count = int(params)
            min_players = plugin.get_config("game.min_players", 6)
            max_players = plugin.get_config("game.max_players", 18)
            
            if player_count < min_players or player_count > max_players:
                await self.send_text(f"❌ 玩家数量必须在 {min_players}-{max_players} 之间")
                return
            
            if len(game_data['players']) > player_count:
                await self.send_text("❌ 当前玩家数已超过设定值")
                return
            
            game_data['settings']['player_count'] = player_count
            game_data['last_activity'] = time.time()
            plugin.gm.save_game_file(room_id, game_data)
            
            await self.send_text(f"✅ 玩家数量已设置为: {player_count}")
            
        except ValueError:
            await self.send_text("❌ 玩家数量必须是数字")
    
    async def _set_roles(self, game_data: Dict, room_id: str, params: str, plugin):
        """设置角色数量"""
        parts = params.split()
        if len(parts) != 2:
            await self.send_text("❌ 格式错误，使用: `/wwg settings roles <角色代码> <数量>`")
            await self.send_text("🔍 使用 `/wwg roles` 查看可用角色代码")
            return
        
        role_code, count_str = parts
        role_code = role_code.upper()
        
        all_roles = plugin.gm.get_all_roles()
        if role_code not in all_roles:
            await self.send_text(f"❌ 未知的角色代码，使用 `/wwg roles` 查看可用角色")
            return
        
        try:
            count = int(count_str)
            if count < 0:
                await self.send_text("❌ 角色数量不能为负数")
                return
            
            game_data['settings']['roles'][role_code] = count
            game_data['last_activity'] = time.time()
            plugin.gm.save_game_file(room_id, game_data)
            
            role_name = all_roles[role_code]['name']
            await self.send_text(f"✅ {role_name} 数量已设置为: {count}")
            
        except ValueError:
            await self.send_text("❌ 角色数量必须是数字")
    
    async def _set_extends(self, game_data: Dict, room_id: str, params: str, plugin):
        """设置扩展包"""
        parts = params.split()
        if len(parts) != 2:
            await self.send_text("❌ 格式错误，使用: `/wwg settings extends <扩展ID> <true/false>`")
            return
        
        ext_id, state_str = parts
        state = state_str.lower() == 'true'
        
        if ext_id not in loaded_extensions:
            await self.send_text("❌ 扩展包不存在")
            return
        
        game_data['settings']['extends'][ext_id] = state
        game_data['last_activity'] = time.time()
        plugin.gm.save_game_file(room_id, game_data)
        
        ext_name = loaded_extensions[ext_id].get('name', ext_id)
        status = "启用" if state else "禁用"
        await self.send_text(f"✅ 扩展包 '{ext_name}' 已{status}")

class WWGStartCommand(WWGBaseCommand):
    """开始游戏命令"""
    
    command_name = "wwg_start"
    command_description = "开始狼人杀游戏"
    command_pattern = r"^/wwg start$"
    
    async def execute(self) -> Tuple[bool, str, bool]:
        sender_qq = self._get_sender_qq()
        
        plugin = getattr(self, 'plugin', None)
        if not plugin:
            await self.send_text("❌ 插件未正确初始化")
            return False, "plugin_error", True
        
        room_id = plugin.gm.find_player_room(sender_qq)
        if not room_id:
            await self.send_text("❌ 你不在任何房间中")
            return False, "not_in_room", True
        
        game_data = active_games[room_id]
        
        if game_data['host'] != sender_qq:
            await self.send_text("❌ 只有房主可以开始游戏")
            return False, "not_host", True
        
        min_players = plugin.get_config("game.min_players", 6)
        if len(game_data['players']) < min_players:
            await self.send_text(f"❌ 至少需要 {min_players} 名玩家才能开始游戏")
            return False, "not_enough_players", True
        
        # 检查角色设置是否合理
        total_roles = sum(game_data['settings']['roles'].values())
        if total_roles != len(game_data['players']):
            await self.send_text(f"❌ 角色总数 ({total_roles}) 与玩家数量 ({len(game_data['players'])}) 不匹配")
            return False, "role_count_mismatch", True
        
        await self.send_text("🎮 游戏开始中...")
        
        # 开始游戏
        await plugin.phase_manager.start_game(game_data, room_id)
        
        return True, "game_started", True

# ================= 投票命令 =================
class WWGVoteCommand(WWGBaseCommand):
    """投票命令"""
    
    command_name = "wwg_vote"
    command_description = "投票处决玩家"
    command_pattern = r"^/wwg vote\s+(?P<player_number>\d+)$"
    
    async def execute(self) -> Tuple[bool, str, bool]:
        sender_qq = self._get_sender_qq()
        player_number = self.matched_groups.get("player_number", "").strip()
        
        plugin = getattr(self, 'plugin', None)
        if not plugin:
            await self.send_text("❌ 插件未正确初始化")
            return False, "plugin_error", True
        
        room_id = plugin.gm.find_player_room(sender_qq)
        if not room_id:
            await self.send_text("❌ 你不在任何游戏房间中")
            return False, "not_in_game", True
        
        game_data = active_games[room_id]
        
        if game_data['phase'] != 'day':
            await self.send_text("❌ 现在不是投票时间")
            return False, "not_voting_phase", True
        
        sender_player = next((p for p in game_data['players'] if p['qq'] == sender_qq), None)
        if not sender_player or not sender_player['alive']:
            await self.send_text("❌ 死亡玩家不能投票")
            return False, "player_dead", True
        
        if player_number not in game_data['player_numbers']:
            await self.send_text("❌ 玩家号不存在")
            return False, "player_not_found", True
        
        target_player = next((p for p in game_data['players'] if str(p['number']) == player_number), None)
        if not target_player or not target_player['alive']:
            await self.send_text("❌ 该玩家已死亡")
            return False, "target_dead", True
        
        # 记录投票
        sender_player['vote'] = int(player_number)
        game_data['last_activity'] = time.time()
        plugin.gm.save_game_file(room_id, game_data)
        
        await self.send_text(f"✅ 你已投票给玩家 {player_number}")
        return True, f"voted:{player_number}", True

# ================= 夜晚行动命令 =================
class WWGCheckCommand(WWGNightActionCommand):
    """预言家查验命令"""
    
    command_name = "wwg_check"
    command_description = "预言家查验玩家身份"
    command_pattern = r"^/wwg check\s+(?P<player_number>\d+)$"
    
    async def execute(self) -> Tuple[bool, str, bool]:
        sender_qq = self._get_sender_qq()
        player_number = self.matched_groups.get("player_number", "").strip()
        
        valid, error_msg, game_data, sender_player = await self._check_night_action_prerequisites(sender_qq)
        if not valid:
            await self.send_text(error_msg)
            return False, "action_failed", True
        
        if sender_player['role'] != 'SEER':
            await self.send_text("❌ 只有预言家可以使用此命令")
            return False, "wrong_role", True
        
        plugin = getattr(self, 'plugin', None)
        room_id = plugin.gm.find_player_room(sender_qq)
        
        if player_number not in game_data['player_numbers']:
            await self.send_text("❌ 玩家号不存在")
            return False, "player_not_found", True
        
        target_player = next((p for p in game_data['players'] if str(p['number']) == player_number), None)
        if not target_player or not target_player['alive']:
            await self.send_text("❌ 该玩家已死亡")
            return False, "target_dead", True
        
        # 记录行动
        game_data['night_actions'][sender_qq] = {
            'action': 'check',
            'target': int(player_number),
            'role': 'SEER',
            'player_qq': sender_qq
        }
        game_data['last_activity'] = time.time()
        plugin.gm.save_game_file(room_id, game_data)
        
        await self.send_text(f"✅ 已选择查验玩家 {player_number}，结果将在夜晚结束时公布")
        return True, f"checked:{player_number}", True

class WWGKillCommand(WWGNightActionCommand):
    """狼人击杀命令"""
    
    command_name = "wwg_kill"
    command_description = "狼人选择击杀目标"
    command_pattern = r"^/wwg kill\s+(?P<player_number>\d+)$"
    
    async def execute(self) -> Tuple[bool, str, bool]:
        sender_qq = self._get_sender_qq()
        player_number = self.matched_groups.get("player_number", "").strip()
        
        valid, error_msg, game_data, sender_player = await self._check_night_action_prerequisites(sender_qq)
        if not valid:
            await self.send_text(error_msg)
            return False, "action_failed", True
        
        plugin = getattr(self, 'plugin', None)
        all_roles = plugin.gm.get_all_roles()
        
        # 检查是否为狼人阵营
        if all_roles[sender_player['role']]['team'] != 'wolf':
            await self.send_text("❌ 只有狼人阵营可以使用此命令")
            return False, "wrong_team", True
        
        # 检查隐狼是否获得刀人能力
        if sender_player['role'] == 'HWOLF':
            alive_wolves = [p for p in game_data['players'] 
                          if p['alive'] and p['role'] != 'HWOLF' and all_roles[p['role']]['team'] == 'wolf']
            if alive_wolves:  # 还有其他狼人存活，隐狼不能刀人
                await self.send_text("❌ 隐狼在其他狼人存活时不能参与击杀")
                return False, "hidden_wolf_cannot_kill", True
            else:
                sender_player['can_kill'] = True
        
        room_id = plugin.gm.find_player_room(sender_qq)
        
        if player_number not in game_data['player_numbers']:
            await self.send_text("❌ 玩家号不存在")
            return False, "player_not_found", True
        
        target_player = next((p for p in game_data['players'] if str(p['number']) == player_number), None)
        if not target_player or not target_player['alive']:
            await self.send_text("❌ 该玩家已死亡")
            return False, "target_dead", True
        
        # 记录行动
        game_data['night_actions'][sender_qq] = {
            'action': 'kill',
            'target': int(player_number),
            'role': sender_player['role'],
            'player_qq': sender_qq
        }
        game_data['last_activity'] = time.time()
        plugin.gm.save_game_file(room_id, game_data)
        
        await self.send_text(f"✅ 已选择击杀玩家 {player_number}")
        return True, f"killed:{player_number}", True

class WWGHealCommand(WWGNightActionCommand):
    """女巫解药命令"""
    
    command_name = "wwg_heal"
    command_description = "女巫使用解药"
    command_pattern = r"^/wwg heal\s+(?P<player_number>\d+)$"
    
    async def execute(self) -> Tuple[bool, str, bool]:
        sender_qq = self._get_sender_qq()
        player_number = self.matched_groups.get("player_number", "").strip()
        
        valid, error_msg, game_data, sender_player = await self._check_night_action_prerequisites(sender_qq)
        if not valid:
            await self.send_text(error_msg)
            return False, "action_failed", True
        
        if sender_player['role'] != 'WITCH':
            await self.send_text("❌ 只有女巫可以使用此命令")
            return False, "wrong_role", True
        
        if not game_data.get('witch_heal_available', True):
            await self.send_text("❌ 解药已使用")
            return False, "heal_used", True
        
        plugin = getattr(self, 'plugin', None)
        room_id = plugin.gm.find_player_room(sender_qq)
        
        if player_number not in game_data['player_numbers']:
            await self.send_text("❌ 玩家号不存在")
            return False, "player_not_found", True
        
        target_player = next((p for p in game_data['players'] if str(p['number']) == player_number), None)
        if not target_player or not target_player['alive']:
            await self.send_text("❌ 该玩家已死亡")
            return False, "target_dead", True
        
        # 记录行动
        game_data['night_actions'][sender_qq] = {
            'action': 'heal',
            'target': int(player_number),
            'role': 'WITCH',
            'player_qq': sender_qq
        }
        game_data['last_activity'] = time.time()
        plugin.gm.save_game_file(room_id, game_data)
        
        await self.send_text(f"✅ 已对玩家 {player_number} 使用解药")
        return True, f"healed:{player_number}", True

class WWGPoisonCommand(WWGNightActionCommand):
    """女巫毒药命令"""
    
    command_name = "wwg_poison"
    command_description = "女巫使用毒药"
    command_pattern = r"^/wwg poison\s+(?P<player_number>\d+)$"
    
    async def execute(self) -> Tuple[bool, str, bool]:
        sender_qq = self._get_sender_qq()
        player_number = self.matched_groups.get("player_number", "").strip()
        
        valid, error_msg, game_data, sender_player = await self._check_night_action_prerequisites(sender_qq)
        if not valid:
            await self.send_text(error_msg)
            return False, "action_failed", True
        
        if sender_player['role'] != 'WITCH':
            await self.send_text("❌ 只有女巫可以使用此命令")
            return False, "wrong_role", True
        
        if not game_data.get('witch_poison_available', True):
            await self.send_text("❌ 毒药已使用")
            return False, "poison_used", True
        
        plugin = getattr(self, 'plugin', None)
        room_id = plugin.gm.find_player_room(sender_qq)
        
        if player_number not in game_data['player_numbers']:
            await self.send_text("❌ 玩家号不存在")
            return False, "player_not_found", True
        
        target_player = next((p for p in game_data['players'] if str(p['number']) == player_number), None)
        if not target_player or not target_player['alive']:
            await self.send_text("❌ 该玩家已死亡")
            return False, "target_dead", True
        
        # 记录行动
        game_data['night_actions'][sender_qq] = {
            'action': 'poison',
            'target': int(player_number),
            'role': 'WITCH',
            'player_qq': sender_qq
        }
        game_data['last_activity'] = time.time()
        plugin.gm.save_game_file(room_id, game_data)
        
        await self.send_text(f"✅ 已对玩家 {player_number} 使用毒药")
        return True, f"poisoned:{player_number}", True

class WWGGuardCommand(WWGNightActionCommand):
    """守卫守护命令"""
    
    command_name = "wwg_guard"
    command_description = "守卫守护玩家"
    command_pattern = r"^/wwg guard\s+(?P<player_number>\d+)$"
    
    async def execute(self) -> Tuple[bool, str, bool]:
        sender_qq = self._get_sender_qq()
        player_number = self.matched_groups.get("player_number", "").strip()
        
        valid, error_msg, game_data, sender_player = await self._check_night_action_prerequisites(sender_qq)
        if not valid:
            await self.send_text(error_msg)
            return False, "action_failed", True
        
        if sender_player['role'] != 'GUARD':
            await self.send_text("❌ 只有守卫可以使用此命令")
            return False, "wrong_role", True
        
        plugin = getattr(self, 'plugin', None)
        room_id = plugin.gm.find_player_room(sender_qq)
        
        if player_number not in game_data['player_numbers']:
            await self.send_text("❌ 玩家号不存在")
            return False, "player_not_found", True
        
        target_player = next((p for p in game_data['players'] if str(p['number']) == player_number), None)
        if not target_player or not target_player['alive']:
            await self.send_text("❌ 该玩家已死亡")
            return False, "target_dead", True
        
        # 检查是否连续守护同一目标
        last_guard = game_data.get('last_guard_target')
        if player_number == last_guard:
            await self.send_text("❌ 不能连续两晚守护同一名玩家")
            return False, "same_guard_target", True
        
        # 记录行动
        game_data['night_actions'][sender_qq] = {
            'action': 'guard',
            'target': int(player_number),
            'role': 'GUARD',
            'player_qq': sender_qq
        }
        game_data['last_activity'] = time.time()
        plugin.gm.save_game_file(room_id, game_data)
        
        await self.send_text(f"✅ 已守护玩家 {player_number}")
        return True, f"guarded:{player_number}", True

class WWGPsychicCommand(WWGNightActionCommand):
    """通灵师查验命令"""
    
    command_name = "wwg_psychic"
    command_description = "通灵师查验具体身份"
    command_pattern = r"^/wwg psychic\s+(?P<player_number>\d+)$"
    
    async def execute(self) -> Tuple[bool, str, bool]:
        sender_qq = self._get_sender_qq()
        player_number = self.matched_groups.get("player_number", "").strip()
        
        valid, error_msg, game_data, sender_player = await self._check_night_action_prerequisites(sender_qq)
        if not valid:
            await self.send_text(error_msg)
            return False, "action_failed", True
        
        if sender_player['role'] != 'PSYC':
            await self.send_text("❌ 只有通灵师可以使用此命令")
            return False, "wrong_role", True
        
        plugin = getattr(self, 'plugin', None)
        room_id = plugin.gm.find_player_room(sender_qq)
        
        if player_number not in game_data['player_numbers']:
            await self.send_text("❌ 玩家号不存在")
            return False, "player_not_found", True
        
        target_player = next((p for p in game_data['players'] if str(p['number']) == player_number), None)
        if not target_player or not target_player['alive']:
            await self.send_text("❌ 该玩家已死亡")
            return False, "target_dead", True
        
        # 记录行动
        game_data['night_actions'][sender_qq] = {
            'action': 'check',
            'target': int(player_number),
            'role': 'PSYC',
            'player_qq': sender_qq
        }
        game_data['last_activity'] = time.time()
        plugin.gm.save_game_file(room_id, game_data)
        
        await self.send_text(f"✅ 已选择查验玩家 {player_number} 的具体身份，结果将在夜晚结束时公布")
        return True, f"psychic_checked:{player_number}", True

class WWGSwapCommand(WWGNightActionCommand):
    """魔术师交换命令"""
    
    command_name = "wwg_swap"
    command_description = "魔术师交换玩家号码牌"
    command_pattern = r"^/wwg swap\s+(?P<player1>\d+)\s+(?P<player2>\d+)$"
    
    async def execute(self) -> Tuple[bool, str, bool]:
        sender_qq = self._get_sender_qq()
        player1 = self.matched_groups.get("player1", "").strip()
        player2 = self.matched_groups.get("player2", "").strip()
        
        valid, error_msg, game_data, sender_player = await self._check_night_action_prerequisites(sender_qq)
        if not valid:
            await self.send_text(error_msg)
            return False, "action_failed", True
        
        if sender_player['role'] != 'MAGI':
            await self.send_text("❌ 只有魔术师可以使用此命令")
            return False, "wrong_role", True
        
        plugin = getattr(self, 'plugin', None)
        room_id = plugin.gm.find_player_room(sender_qq)
        
        if player1 not in game_data['player_numbers'] or player2 not in game_data['player_numbers']:
            await self.send_text("❌ 玩家号不存在")
            return False, "player_not_found", True
        
        if player1 == player2:
            await self.send_text("❌ 不能交换同一名玩家")
            return False, "same_player", True
        
        target1 = next((p for p in game_data['players'] if str(p['number']) == player1), None)
        target2 = next((p for p in game_data['players'] if str(p['number']) == player2), None)
        if not target1 or not target1['alive'] or not target2 or not target2['alive']:
            await self.send_text("❌ 玩家已死亡")
            return False, "player_dead", True
        
        # 记录行动
        game_data['night_actions'][sender_qq] = {
            'action': 'swap',
            'target1': int(player1),
            'target2': int(player2),
            'role': 'MAGI',
            'player_qq': sender_qq
        }
        game_data['last_activity'] = time.time()
        plugin.gm.save_game_file(room_id, game_data)
        
        await self.send_text(f"✅ 已交换玩家 {player1} 和 {player2} 的号码牌")
        return True, f"swapped:{player1}:{player2}", True

class WWGPaintCommand(WWGNightActionCommand):
    """画皮伪装命令"""
    
    command_name = "wwg_paint"
    command_description = "画皮伪装成死亡玩家身份"
    command_pattern = r"^/wwg paint\s+(?P<player_number>\d+)$"
    
    async def execute(self) -> Tuple[bool, str, bool]:
        sender_qq = self._get_sender_qq()
        player_number = self.matched_groups.get("player_number", "").strip()
        
        valid, error_msg, game_data, sender_player = await self._check_night_action_prerequisites(sender_qq)
        if not valid:
            await self.send_text(error_msg)
            return False, "action_failed", True
        
        if sender_player['role'] != 'PAINT':
            await self.send_text("❌ 只有画皮可以使用此命令")
            return False, "wrong_role", True
        
        # 检查是否是第二夜及以后
        if game_data.get('night_count', 1) < 2:
            await self.send_text("❌ 画皮从第二夜开始才能使用能力")
            return False, "too_early", True
        
        # 检查是否已使用过能力
        if game_data.get('paint_disguise') and game_data['paint_disguise'].get('painter_qq') == sender_qq:
            await self.send_text("❌ 画皮每局只能使用一次能力")
            return False, "already_used", True
        
        plugin = getattr(self, 'plugin', None)
        room_id = plugin.gm.find_player_room(sender_qq)
        
        if player_number not in game_data['player_numbers']:
            await self.send_text("❌ 玩家号不存在")
            return False, "player_not_found", True
        
        target_player = next((p for p in game_data['players'] if str(p['number']) == player_number), None)
        if not target_player or target_player['alive']:
            await self.send_text("❌ 只能伪装成已死亡玩家的身份")
            return False, "target_alive", True
        
        # 记录行动
        game_data['night_actions'][sender_qq] = {
            'action': 'paint',
            'target': int(player_number),
            'role': 'PAINT',
            'player_qq': sender_qq
        }
        game_data['last_activity'] = time.time()
        plugin.gm.save_game_file(room_id, game_data)
        
        await self.send_text(f"✅ 已选择伪装成玩家 {player_number} 的身份")
        return True, f"painted:{player_number}", True

class WWGConnectCommand(WWGNightActionCommand):
    """丘比特连接命令"""
    
    command_name = "wwg_connect"
    command_description = "丘比特连接两名玩家成为情侣"
    command_pattern = r"^/wwg connect\s+(?P<player1>\d+)\s+(?P<player2>\d+)$"
    
    async def execute(self) -> Tuple[bool, str, bool]:
        sender_qq = self._get_sender_qq()
        player1 = self.matched_groups.get("player1", "").strip()
        player2 = self.matched_groups.get("player2", "").strip()
        
        valid, error_msg, game_data, sender_player = await self._check_night_action_prerequisites(sender_qq)
        if not valid:
            await self.send_text(error_msg)
            return False, "action_failed", True
        
        if sender_player['role'] != 'CUPID':
            await self.send_text("❌ 只有丘比特可以使用此命令")
            return False, "wrong_role", True
        
        # 检查是否是第一夜
        if game_data.get('night_count', 1) != 1:
            await self.send_text("❌ 丘比特只能在第一夜使用能力")
            return False, "not_first_night", True
        
        plugin = getattr(self, 'plugin', None)
        room_id = plugin.gm.find_player_room(sender_qq)
        
        if player1 not in game_data['player_numbers'] or player2 not in game_data['player_numbers']:
            await self.send_text("❌ 玩家号不存在")
            return False, "player_not_found", True
        
        if player1 == player2:
            await self.send_text("❌ 不能连接同一名玩家")
            return False, "same_player", True
        
        target1 = next((p for p in game_data['players'] if str(p['number']) == player1), None)
        target2 = next((p for p in game_data['players'] if str(p['number']) == player2), None)
        if not target1 or not target1['alive'] or not target2 or not target2['alive']:
            await self.send_text("❌ 玩家已死亡")
            return False, "player_dead", True
        
        # 记录行动
        game_data['night_actions'][sender_qq] = {
            'action': 'connect',
            'target1': int(player1),
            'target2': int(player2),
            'role': 'CUPID',
            'player_qq': sender_qq
        }
        game_data['last_activity'] = time.time()
        plugin.gm.save_game_file(room_id, game_data)
        
        await self.send_text(f"✅ 已连接玩家 {player1} 和 {player2} 成为情侣")
        return True, f"connected:{player1}:{player2}", True

class WWGSkipCommand(WWGNightActionCommand):
    """跳过行动命令"""
    
    command_name = "wwg_skip"
    command_description = "跳过夜晚行动"
    command_pattern = r"^/wwg skip$"
    
    async def execute(self) -> Tuple[bool, str, bool]:
        sender_qq = self._get_sender_qq()
        
        valid, error_msg, game_data, sender_player = await self._check_night_action_prerequisites(sender_qq)
        if not valid:
            await self.send_text(error_msg)
            return False, "action_failed", True
        
        plugin = getattr(self, 'plugin', None)
        room_id = plugin.gm.find_player_room(sender_qq)
        
        # 记录跳过行动
        game_data['night_actions'][sender_qq] = {
            'action': 'skip',
            'role': sender_player['role'],
            'player_qq': sender_qq
        }
        game_data['last_activity'] = time.time()
        plugin.gm.save_game_file(room_id, game_data)
        
        await self.send_text("✅ 已跳过本次行动")
        return True, "skipped", True

# ================= 白天行动命令 =================
class WWGShootCommand(WWGBaseCommand):
    """猎人开枪命令"""
    
    command_name = "wwg_shoot"
    command_description = "猎人开枪带走玩家"
    command_pattern = r"^/wwg shoot\s+(?P<player_number>\d+)$"
    
    async def execute(self) -> Tuple[bool, str, bool]:
        sender_qq = self._get_sender_qq()
        player_number = self.matched_groups.get("player_number", "").strip()
        
        plugin = getattr(self, 'plugin', None)
        if not plugin:
            await self.send_text("❌ 插件未正确初始化")
            return False, "plugin_error", True
        
        room_id = plugin.gm.find_player_room(sender_qq)
        if not room_id:
            await self.send_text("❌ 你不在任何游戏房间中")
            return False, "not_in_game", True
        
        game_data = active_games[room_id]
        
        sender_player = next((p for p in game_data['players'] if p['qq'] == sender_qq), None)
        if not sender_player:
            await self.send_text("❌ 玩家信息错误")
            return False, "player_error", True
        
        if sender_player['role'] != 'HUNT':
            await self.send_text("❌ 只有猎人可以使用此命令")
            return False, "wrong_role", True
        
        # 检查是否为猎人复仇阶段
        if game_data.get('hunter_revenge') != sender_qq:
            await self.send_text("❌ 现在不是你的复仇时间")
            return False, "not_revenge_time", True
        
        if player_number not in game_data['player_numbers']:
            await self.send_text("❌ 玩家号不存在")
            return False, "player_not_found", True
        
        target_player = next((p for p in game_data['players'] if str(p['number']) == player_number), None)
        if not target_player or not target_player['alive']:
            await self.send_text("❌ 该玩家已死亡")
            return False, "target_dead", True
        
        # 执行射击
        target_player['alive'] = False
        target_player['death_reason'] = 'shot'
        target_player['death_time'] = time.time()
        
        # 清除猎人复仇状态
        game_data['hunter_revenge'] = None
        game_data['last_activity'] = time.time()
        plugin.gm.save_game_file(room_id, game_data)
        
        # 通知所有玩家
        shoot_msg = f"🔫 猎人玩家 {sender_player['number']} 开枪带走了玩家 {player_number}"
        await plugin.resolver._broadcast_to_players(game_data, shoot_msg)
        
        return True, f"shot:{player_number}", True

class WWGExplodeCommand(WWGBaseCommand):
    """白狼王自爆命令"""
    
    command_name = "wwg_explode"
    command_description = "白狼王自爆并带走玩家"
    command_pattern = r"^/wwg explode\s+(?P<player_number>\d+)$"
    
    async def execute(self) -> Tuple[bool, str, bool]:
        sender_qq = self._get_sender_qq()
        player_number = self.matched_groups.get("player_number", "").strip()
        
        plugin = getattr(self, 'plugin', None)
        if not plugin:
            await self.send_text("❌ 插件未正确初始化")
            return False, "plugin_error", True
        
        room_id = plugin.gm.find_player_room(sender_qq)
        if not room_id:
            await self.send_text("❌ 你不在任何游戏房间中")
            return False, "not_in_game", True
        
        game_data = active_games[room_id]
        
        if game_data['phase'] != 'day':
            await self.send_text("❌ 白狼王只能在白天自爆")
            return False, "not_day", True
        
        sender_player = next((p for p in game_data['players'] if p['qq'] == sender_qq), None)
        if not sender_player or not sender_player['alive']:
            await self.send_text("❌ 死亡玩家不能行动")
            return False, "player_dead", True
        
        if sender_player['role'] != 'WWOLF':
            await self.send_text("❌ 只有白狼王可以使用此命令")
            return False, "wrong_role", True
        
        if player_number not in game_data['player_numbers']:
            await self.send_text("❌ 玩家号不存在")
            return False, "player_not_found", True
        
        target_player = next((p for p in game_data['players'] if str(p['number']) == player_number), None)
        if not target_player or not target_player['alive']:
            await self.send_text("❌ 该玩家已死亡")
            return False, "target_dead", True
        
        # 执行自爆
        sender_player['alive'] = False
        sender_player['death_reason'] = 'exploded'
        target_player['alive'] = False
        target_player['death_reason'] = 'exploded'
        
        game_data['last_activity'] = time.time()
        plugin.gm.save_game_file(room_id, game_data)
        
        # 通知所有玩家并立即进入黑夜
        explode_msg = (
            f"💥 **白狼王自爆！**\n\n"
            f"玩家 {sender_player['number']} (白狼王) 自爆并带走了玩家 {player_number}\n"
            f"立即进入黑夜！"
        )
        await plugin.resolver._broadcast_to_players(game_data, explode_msg)
        
        # 进入黑夜
        await plugin.phase_manager._start_night_phase(game_data, room_id)
        
        return True, f"exploded:{player_number}", True

# ================= 档案和记录查询命令 =================
class WWGProfileCommand(WWGBaseCommand):
    """查询档案命令"""
    
    command_name = "wwg_profile"
    command_description = "查询玩家档案"
    command_pattern = r"^/wwg profile(?:\s+(?P<target_qq>\d+))?$"
    
    async def execute(self) -> Tuple[bool, str, bool]:
        sender_qq = self._get_sender_qq()
        target_qq = self.matched_groups.get("target_qq", "").strip()
        
        # 如果没有指定QQ号，则查询自己的档案
        if not target_qq:
            target_qq = sender_qq
        
        if target_qq not in player_profiles:
            if target_qq == sender_qq:
                await self.send_text("❌ 你还没有游戏记录")
            else:
                await self.send_text("❌ 该玩家还没有游戏记录")
            return False, "no_profile", True
        
        profile = player_profiles[target_qq]
        
        # 计算胜率
        total_games = profile['games_played']
        if total_games > 0:
            win_rate = (profile['games_won'] / total_games) * 100
            recent_games = profile['recent_win_rate']
            recent_win_rate = (sum(recent_games) / len(recent_games)) * 100 if recent_games else 0
        else:
            win_rate = 0
            recent_win_rate = 0
        
        profile_text = (
            f"📊 **玩家档案** - {target_qq}\n\n"
            f"🎮 总对局数: {total_games}\n"
            f"🏆 胜利场次: {profile['games_won']}\n"
            f"💔 失败场次: {profile['games_lost']}\n"
            f"📈 总胜率: {win_rate:.1f}%\n"
            f"🔥 近期胜率: {recent_win_rate:.1f}%\n"
            f"🔪 击杀数: {profile.get('kills', 0)}\n"
            f"🗳️ 票杀数: {profile.get('votes', 0)}\n"
        )
        
        if profile['recent_win_rate']:
            win_emojis = ''.join('✅' if w else '❌' for w in profile['recent_win_rate'])
            profile_text += f"📋 最近{len(profile['recent_win_rate'])}场: {win_emojis}"
        
        await self.send_text(profile_text)
        return True, "profile_shown", True

class WWGArchiveCommand(WWGBaseCommand):
    """查询对局记录命令"""
    
    command_name = "wwg_archive"
    command_description = "查询对局记录"
    command_pattern = r"^/wwg archive\s+(?P<archive_code>\w+)$"
    
    async def execute(self) -> Tuple[bool, str, bool]:
        archive_code = self.matched_groups.get("archive_code", "").strip().upper()
        
        if archive_code not in game_archives:
            await self.send_text("❌ 对局记录不存在")
            return False, "archive_not_found", True
        
        game_data = game_archives[archive_code]
        
        # 生成对局详情
        winner = game_data.get('winner', 'unknown')
        winner_name = {
            'village': '🏰 村庄阵营',
            'wolf': '🐺 狼人阵营',
            'lovers': '💕 情侣阵营',
            'draw': '🤝 平局',
            'unknown': '未知'
        }.get(winner, '未知')
        
        start_time = datetime.fromisoformat(game_data['start_time']).strftime("%Y-%m-%d %H:%M")
        end_time = datetime.fromisoformat(game_data['end_time']).strftime("%Y-%m-%d %H:%M") if game_data.get('end_time') else "未结束"
        
        plugin = getattr(self, 'plugin', None)
        all_roles = plugin.gm.get_all_roles() if plugin else BASE_ROLES
        
        archive_text = (
            f"📜 **对局记录** - {archive_code}\n\n"
            f"🏆 胜利方: {winner_name}\n"
            f"⏰ 开始时间: {start_time}\n"
            f"⏱️ 结束时间: {end_time}\n"
            f"👑 房主: {game_data['host']}\n"
            f"👥 玩家数: {len(game_data['players'])}\n\n"
            f"**玩家详情**:\n"
        )
        
        for player in game_data['players']:
            role_name = all_roles[player['role']]['name']
            status = "✅ 存活" if player['alive'] else "❌ 死亡"
            death_reason = f" ({player.get('death_reason')})" if not player['alive'] else ""
            archive_text += f"玩家 {player['number']}: {role_name} - {status}{death_reason}\n"
        
        await self.send_text(archive_text)
        return True, "archive_shown", True

# ================= 插件注册 =================
@register_plugin
class WerewolfGamePlugin(WerewolfGamePlugin):
    """狼人杀游戏插件"""
    
    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        return [
            # 游戏管理命令
            (WWGHelpCommand.get_command_info(), WWGHelpCommand),
            (WWGRolesCommand.get_command_info(), WWGRolesCommand),
            (WWGHostCommand.get_command_info(), WWGHostCommand),
            (WWGJoinCommand.get_command_info(), WWGJoinCommand),
            (WWGSettingsCommand.get_command_info(), WWGSettingsCommand),
            (WWGStartCommand.get_command_info(), WWGStartCommand),
            (WWGVoteCommand.get_command_info(), WWGVoteCommand),
            
            # 夜晚行动命令
            (WWGCheckCommand.get_command_info(), WWGCheckCommand),
            (WWGKillCommand.get_command_info(), WWGKillCommand),
            (WWGHealCommand.get_command_info(), WWGHealCommand),
            (WWGPoisonCommand.get_command_info(), WWGPoisonCommand),
            (WWGGuardCommand.get_command_info(), WWGGuardCommand),
            (WWGPsychicCommand.get_command_info(), WWGPsychicCommand),
            (WWGSwapCommand.get_command_info(), WWGSwapCommand),
            (WWGPaintCommand.get_command_info(), WWGPaintCommand),
            (WWGConnectCommand.get_command_info(), WWGConnectCommand),
            (WWGSkipCommand.get_command_info(), WWGSkipCommand),
            
            # 白天行动命令
            (WWGShootCommand.get_command_info(), WWGShootCommand),
            (WWGExplodeCommand.get_command_info(), WWGExplodeCommand),
            
            # 档案和记录查询命令
            (WWGProfileCommand.get_command_info(), WWGProfileCommand),
            (WWGArchiveCommand.get_command_info(), WWGArchiveCommand),
        ]