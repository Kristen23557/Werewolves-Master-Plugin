import os
import json
import random
import time
import datetime
import hashlib
import asyncio
import importlib.util
from typing import List, Tuple, Type, Dict, Any, Optional
from src.plugin_system import (
    BasePlugin,
    register_plugin,
    BaseCommand,
    ComponentInfo,
    ConfigField
)
from src.plugin_system.apis import send_api

# --- 全局状态存储 ---
rooms = {}  # {room_id: room_data}
player_profiles = {}  # {qq_number: profile_data}
active_games = {}  # {room_id: game_data}
game_archives = {}  # {game_code: archive_data}

# --- 基础角色定义 ---
BASE_ROLES = {
    "vil": {
        "name": "村民", 
        "team": "village", 
        "sub_role": False, 
        "night_action": False,
        "description": "普通村民，没有特殊能力，依靠推理和投票找出狼人"
    },
    "seer": {
        "name": "预言家", 
        "team": "village", 
        "sub_role": True, 
        "night_action": True,
        "action_command": "check",
        "description": "每晚可以查验一名玩家的身份阵营",
        "action_prompt": "请选择要查验的玩家号码"
    },
    "witch": {
        "name": "女巫", 
        "team": "village", 
        "sub_role": True, 
        "night_action": True,
        "action_command": "potion",
        "has_antidote": True,
        "has_poison": True,
        "description": "拥有一瓶解药和一瓶毒药，每晚只能使用一瓶",
        "action_prompt": "选择行动: 1.使用解药救人或 2.使用毒药杀人 (输入1或2)"
    },
    "hunt": {
        "name": "猎人", 
        "team": "village", 
        "sub_role": True, 
        "night_action": False,
        "special_action": "revenge",
        "description": "被狼人杀死或被投票出局时，可以开枪带走一名玩家",
        "can_revenge": True
    },
    "wolf": {
        "name": "狼人", 
        "team": "werewolf", 
        "sub_role": False, 
        "night_action": True,
        "action_command": "kill", 
        "vote_action": True,
        "description": "每晚与其他狼人共同讨论并选择一名玩家杀害",
        "action_prompt": "请与其他狼人讨论并选择要杀害的玩家号码"
    }
}

# --- 扩展包基类 ---
class WerewolfDLC:
    """狼人杀扩展包基类"""
    
    def __init__(self):
        self.dlc_id = ""  # 扩展包ID
        self.dlc_name = ""  # 扩展包名称
        self.roles = {}  # 角色定义
        self.author = ""  # 作者
        self.version = "1.0.0"  # 版本
    
    async def on_game_start(self, game_data: Dict) -> None:
        """游戏开始时调用"""
        pass
    
    async def on_night_start(self, game_data: Dict) -> None:
        """夜晚开始时调用"""
        pass
    
    async def on_day_start(self, game_data: Dict) -> None:
        """白天开始时调用"""
        pass
    
    async def on_player_death(self, game_data: Dict, dead_player: str, reason: str, killer: str) -> None:
        """玩家死亡时调用"""
        pass
    
    async def on_game_end(self, game_data: Dict, winner: str) -> None:
        """游戏结束时调用"""
        pass
    
    async def handle_command(self, user_id: str, game_data: Dict, action: str, params: str) -> bool:
        """处理扩展包专属命令"""
        return False
    
    async def modify_seer_result(self, game_data: Dict, original_result: str, **kwargs) -> str:
        """修改预言家查验结果"""
        return original_result
    
    async def modify_wolf_kill(self, game_data: Dict, default_value: bool, **kwargs) -> bool:
        """修改狼人杀人效果"""
        return default_value
    
    async def modify_guard_protect(self, game_data: Dict, default_value: bool, **kwargs) -> bool:
        """修改守卫守护效果"""
        return default_value
    
    async def modify_witch_antidote(self, game_data: Dict, default_value: bool, **kwargs) -> bool:
        """修改女巫解药效果"""
        return default_value
    
    async def modify_witch_poison(self, game_data: Dict, default_value: bool, **kwargs) -> bool:
        """修改女巫毒药效果"""
        return default_value

# --- 插件主类 ---
@register_plugin
class WerewolfGamePlugin(BasePlugin):
    """狼人杀游戏插件"""

    plugin_name = "Werewolves-Master-Plugin"
    plugin_description = "纯指令驱动的狼人杀游戏"
    plugin_version = "1.0.0"
    plugin_author = "KArabella"
    enable_plugin = True

    dependencies = []
    python_dependencies = []

    config_file_name = "config.toml"
    config_section_descriptions = {
        "plugin": "插件基础配置",
        "game": "游戏规则配置"
    }

    config_schema = {
        "plugin": {
            "enabled": ConfigField(type=bool, default=True, description="是否启用插件"),
            "config_version": ConfigField(type=str, default="1.0.0", description="配置文件版本"),
        },
        "game": {
            "room_timeout": ConfigField(type=int, default=1200, description="房间超时时间(秒)"),
            "game_timeout": ConfigField(type=int, default=1800, description="对局超时时间(秒)"),
            "night_duration": ConfigField(type=int, default=300, description="夜晚持续时间(秒)"),
            "day_duration": ConfigField(type=int, default=300, description="白天持续时间(秒)"),
            "min_players": ConfigField(type=int, default=6, description="最小玩家数"),
            "max_players": ConfigField(type=int, default=18, description="最大玩家数"),
            "revenge_time": ConfigField(type=int, default=60, description="猎人复仇时间(秒)")
        }
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.games_dir = os.path.join(os.path.dirname(__file__), "games")
        self.finished_dir = os.path.join(self.games_dir, "finished")
        self.users_dir = os.path.join(os.path.dirname(__file__), "users")
        self.dlcs_dir = os.path.join(os.path.dirname(__file__), "dlcs")
        self._ensure_directories()
        self._load_profiles()
        self.active_dlcs = {}  # 激活的扩展包 {dlc_id: dlc_instance}
        self._load_dlcs()
        self._load_archives()
        self.cleanup_task = None

    def _ensure_directories(self):
        """确保所需目录存在"""
        os.makedirs(self.games_dir, exist_ok=True)
        os.makedirs(self.finished_dir, exist_ok=True)
        os.makedirs(self.users_dir, exist_ok=True)
        os.makedirs(self.dlcs_dir, exist_ok=True)

    def _load_profiles(self):
        """加载玩家档案"""
        global player_profiles
        for filename in os.listdir(self.users_dir):
            if filename.endswith('.json'):
                try:
                    with open(os.path.join(self.users_dir, filename), 'r', encoding='utf-8') as f:
                        qq_num = filename[:-5]  # 移除.json
                        player_profiles[qq_num] = json.load(f)
                except Exception as e:
                    print(f"加载玩家档案 {filename} 失败: {e}")

    def _load_dlcs(self):
        """加载扩展包"""
        for dlc_name in os.listdir(self.dlcs_dir):
            dlc_path = os.path.join(self.dlcs_dir, dlc_name)
            if os.path.isdir(dlc_path):
                # 尝试加载Python扩展包
                py_file = os.path.join(dlc_path, f"{dlc_name}.py")
                if os.path.exists(py_file):
                    try:
                        # 动态导入扩展包
                        spec = importlib.util.spec_from_file_location(dlc_name, py_file)
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        
                        # 获取扩展包实例
                        if hasattr(module, dlc_name):
                            dlc_instance = getattr(module, dlc_name)()
                            self.active_dlcs[dlc_instance.dlc_id] = dlc_instance
                            print(f"✅ 加载扩展包: {dlc_instance.dlc_name} v{dlc_instance.version}")
                        
                    except Exception as e:
                        print(f"❌ 加载扩展包 {dlc_name} 失败: {e}")

    def _load_archives(self):
        """加载对局记录"""
        global game_archives
        for filename in os.listdir(self.finished_dir):
            if filename.endswith('.json'):
                try:
                    with open(os.path.join(self.finished_dir, filename), 'r', encoding='utf-8') as f:
                        game_data = json.load(f)
                        game_code = game_data.get('game_code')
                        if game_code:
                            game_archives[game_code] = game_data
                except Exception as e:
                    print(f"加载对局记录 {filename} 失败: {e}")

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        return [(WerewolfCommand.get_command_info(), WerewolfCommand)]

    async def on_enable(self):
        """插件启用时启动清理任务"""
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def on_disable(self):
        """插件禁用时停止清理任务"""
        if self.cleanup_task:
            self.cleanup_task.cancel()

    async def _cleanup_loop(self):
        """定期清理超时房间"""
        while True:
            try:
                await self._cleanup_timeout_rooms()
                await asyncio.sleep(60)  # 每分钟检查一次
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"清理任务出错: {e}")

    async def _cleanup_timeout_rooms(self):
        """清理超时房间"""
        current_time = time.time()
        room_timeout = self.get_config("game.room_timeout", 1200)
        game_timeout = self.get_config("game.game_timeout", 1800)
        
        # 清理等待中的房间
        for room_id in list(rooms.keys()):
            room = rooms[room_id]
            if room["status"] == "waiting" and current_time - room["created_time"] > room_timeout:
                # 通知玩家房间已过期
                group_id = room["group_id"]
                if group_id and group_id != "private":
                    try:
                        await send_api.text_to_group(
                            text=f"⏰ 房间 {room_id} 因超时已自动关闭。",
                            group_id=group_id,
                            platform="qq"
                        )
                    except:
                        pass
                
                del rooms[room_id]
                # 删除对应的游戏文件
                game_file = os.path.join(self.games_dir, f"{room_id}.json")
                if os.path.exists(game_file):
                    os.remove(game_file)
        
        # 清理进行中的游戏
        for room_id in list(active_games.keys()):
            game = active_games[room_id]
            if current_time - game.get("game_start", current_time) > game_timeout:
                await self._end_game_due_to_timeout(room_id)

    async def _end_game_due_to_timeout(self, room_id: str):
        """因超时结束游戏"""
        if room_id in active_games:
            game_data = active_games[room_id]
            group_id = game_data.get("group_id")
            
            # 归档游戏记录
            await self._archive_game(game_data, "超时结束")
            
            # 通知玩家
            if group_id and group_id != "private":
                try:
                    await send_api.text_to_group(
                        text="⏰ 游戏因超时自动结束。",
                        group_id=group_id,
                        platform="qq"
                    )
                except:
                    pass
            
            # 清理状态
            if room_id in rooms:
                del rooms[room_id]
            del active_games[room_id]

    async def _archive_game(self, game_data: Dict, winner: str):
        """归档游戏记录"""
        game_code = hashlib.md5(str(time.time()).encode()).hexdigest()[:12]
        
        archive_data = {
            "game_code": game_code,
            "room_id": game_data["room_id"],
            "start_time": datetime.datetime.fromtimestamp(game_data["game_start"]).isoformat(),
            "end_time": datetime.datetime.now().isoformat(),
            "winner": winner,
            "players": []
        }
        
        # 整理玩家信息
        for player_id, role_info in game_data["players"].items():
            player_data = {
                "qq": player_id,
                "number": role_info["player_number"],
                "role": role_info["name"],
                "team": role_info["team"],
                "alive": role_info.get("alive", True),
                "death_reason": role_info.get("death_reason", ""),
                "killer": role_info.get("killer", "")
            }
            archive_data["players"].append(player_data)
        
        # 保存归档文件
        file_path = os.path.join(self.finished_dir, f"{game_code}.json")
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(archive_data, f, ensure_ascii=False, indent=2)
            game_archives[game_code] = archive_data
        except Exception as e:
            print(f"归档游戏记录失败: {e}")

    # DLC管理方法
    def get_dlc_roles(self, dlc_id: str) -> Dict:
        """获取扩展包的角色定义"""
        if dlc_id in self.active_dlcs:
            return self.active_dlcs[dlc_id].roles
        return {}

    async def call_dlc_hook(self, hook_name: str, game_data: Dict, **kwargs):
        """调用扩展包钩子"""
        enabled_dlcs = game_data.get("settings", {}).get("enabled_dlcs", [])
        
        for dlc_id in enabled_dlcs:
            if dlc_id in self.active_dlcs:
                dlc = self.active_dlcs[dlc_id]
                if hasattr(dlc, hook_name):
                    try:
                        method = getattr(dlc, hook_name)
                        if asyncio.iscoroutinefunction(method):
                            await method(game_data, **kwargs)
                        else:
                            method(game_data, **kwargs)
                    except Exception as e:
                        print(f"调用扩展包 {dlc_id} 的 {hook_name} 失败: {e}")

    async def call_dlc_modifier(self, modifier_name: str, game_data: Dict, default_value, **kwargs):
        """调用扩展包修改器，返回修改后的值"""
        enabled_dlcs = game_data.get("settings", {}).get("enabled_dlcs", [])
        result = default_value
        
        for dlc_id in enabled_dlcs:
            if dlc_id in self.active_dlcs:
                dlc = self.active_dlcs[dlc_id]
                if hasattr(dlc, modifier_name):
                    try:
                        method = getattr(dlc, modifier_name)
                        if asyncio.iscoroutinefunction(method):
                            new_result = await method(game_data, result, **kwargs)
                        else:
                            new_result = method(game_data, result, **kwargs)
                        
                        if new_result is not None:
                            result = new_result
                    except Exception as e:
                        print(f"调用扩展包 {dlc_id} 的 {modifier_name} 失败: {e}")
        
        return result

# --- 命令处理类 ---
class WerewolfCommand(BaseCommand):
    """狼人杀游戏命令处理器"""

    command_name = "WerewolfGame"
    command_description = "狼人杀游戏命令。使用 /wwg 帮助 查看详细用法"
    command_pattern = r"^/wwg\s+(?P<action>\S+)(?:\s+(?P<params>.*))?$"
    intercept_message = True

    @property
    def plugin_instance(self):
        """动态获取插件实例"""
        from src.plugin_system.plugin_manager import get_plugin_instance
        return get_plugin_instance("Werewolves-Master-Plugin")

    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        """执行命令逻辑"""
        try:
            # 安全处理匹配组
            if self.matched_groups is None:
                return await self._show_help()
                
            matched_groups = self.matched_groups
            action = matched_groups.get("action", "").lower().strip()
            params = matched_groups.get("params", "").strip()

            # 获取用户和群组信息
            user_id = str(self.message.message_info.user_info.user_id)
            group_info = self.message.message_info.group_info
            group_id = str(group_info.group_id) if group_info else "private"

            # 检查是否是角色查询命令
            if action == "roles":
                return await self._handle_role_commands(params)

            # 检查是否是DLC管理命令
            if action == "dlc":
                return await self._handle_dlc_management(user_id, params)

            # 检查是否是游戏内行动命令
            game_action_handled = await self._handle_game_actions(user_id, group_id, action, params)
            if game_action_handled:
                return True, "游戏行动已处理", True

            # 常规命令处理
            return await self._handle_regular_commands(user_id, group_id, action, params)
                
        except Exception as e:
            print(f"ERROR in execute: {e}")
            import traceback
            traceback.print_exc()
            await self.send_text("❌ 命令执行出错，请稍后重试。")
            return False, f"命令执行异常: {e}", True

    async def _handle_regular_commands(self, user_id: str, group_id: str, action: str, params: str) -> Tuple[bool, str, bool]:
        """处理常规命令"""
        if action in ["帮助", "help"]:
            return await self._show_help()
        elif action == "host":
            return await self._create_room(user_id, group_id)
        elif action == "join":
            return await self._join_room(user_id, group_id, params)
        elif action == "settings":
            return await self._room_settings(user_id, group_id, params)
        elif action == "start":
            return await self._start_game(user_id, group_id)
        elif action == "profile":
            return await self._show_profile(user_id, params)
        elif action == "archive":
            return await self._show_archive(params)
        elif action == "list":
            return await self._list_rooms()
        else:
            await self.send_text("❌ 未知命令。使用 /wwg 帮助 查看可用命令。")
            return False, "未知命令", True

    async def _handle_dlc_management(self, user_id: str, params: str) -> Tuple[bool, str, bool]:
        """处理DLC管理命令"""
        params_list = params.split()
        dlc_action = params_list[0] if params_list else "list"
        dlc_params = " ".join(params_list[1:]) if len(params_list) > 1 else ""
        
        if dlc_action == "list":
            plugin = self.plugin_instance
            if not plugin.active_dlcs:
                await self.send_text("❌ 没有可用的扩展包。")
                return True, "没有可用扩展包", True
            
            msg = "🎮 **可用扩展包列表**\n\n"
            for dlc_id, dlc in plugin.active_dlcs.items():
                msg += f"🔹 {dlc.dlc_name} (ID: {dlc_id})\n"
                msg += f"   作者: {dlc.author}\n"
                msg += f"   版本: {dlc.version}\n"
                msg += f"   角色数: {len(dlc.roles)}\n"
                msg += "   ---\n"
            
            await self.send_text(msg)
            return True, "已显示扩展包列表", True
        else:
            await self.send_text("❌ 未知的DLC命令。使用: /wwg dlc list")
            return False, "未知DLC命令", True

    async def _handle_game_actions(self, user_id: str, group_id: str, action: str, params: str) -> bool:
        """处理游戏内行动命令"""
        # 查找用户所在的游戏
        game_data = None
        room_id = None
        
        for rid, game in active_games.items():
            if user_id in game.get("players", {}) and group_id == game.get("group_id"):
                game_data = game
                room_id = rid
                break
        
        if not game_data:
            return False

        # 先尝试处理扩展包命令
        dlc_handled = await self._handle_dlc_game_commands(user_id, game_data, action, params)
        if dlc_handled:
            return True

        # 游戏行动命令处理
        if action == "vote":
            return await self._handle_vote(user_id, game_data, params)
        elif action == "skip":
            return await self._handle_skip(user_id, game_data)
        elif action in ["check", "kill", "potion"]:
            return await self._handle_night_action(user_id, game_data, action, params)
        elif action == "revenge":
            return await self._handle_revenge(user_id, game_data, params)
        elif action == "status":
            return await self._show_game_status(game_data)
        elif action == "explode":
            return await self._handle_white_wolf_explode(user_id, game_data, params)
        
        return False

    async def _handle_dlc_game_commands(self, user_id: str, game_data: Dict, action: str, params: str) -> bool:
        """处理游戏内的DLC命令"""
        try:
            plugin = self.plugin_instance
            enabled_dlcs = game_data.get("settings", {}).get("enabled_dlcs", [])
            
            for dlc_id in enabled_dlcs:
                if dlc_id in plugin.active_dlcs:
                    dlc = plugin.active_dlcs[dlc_id]
                    handled = await dlc.handle_command(user_id, game_data, action, params)
                    if handled:
                        return True
            
            return False
        except Exception as e:
            print(f"ERROR in _handle_dlc_game_commands: {e}")
            return False

    async def _handle_role_commands(self, params: str) -> Tuple[bool, str, bool]:
        """处理角色查询命令"""
        if params.strip().lower() == "list":
            return await self._show_all_roles()
        else:
            await self.send_text("❌ 角色命令格式错误。使用: /wwg roles list")
            return False, "角色命令格式错误", True

    async def _show_all_roles(self) -> Tuple[bool, str, bool]:
        """显示所有可用角色"""
        plugin = self.plugin_instance
        
        # 基础角色
        base_roles_msg = "🎭 **基础角色列表**\n\n"
        for role_code, role_info in BASE_ROLES.items():
            team_emoji = "🐺" if role_info["team"] == "werewolf" else "👨‍🌾"
            base_roles_msg += f"{team_emoji} {role_info['name']} ({role_code})\n"
            base_roles_msg += f"   阵营: {self._get_team_name(role_info['team'])}\n"
            base_roles_msg += f"   类型: {'神民' if role_info.get('sub_role') else '普通'}\n"
            if role_info.get('night_action'):
                base_roles_msg += f"   夜晚行动: /wwg {role_info['action_command']}\n"
            base_roles_msg += f"   描述: {role_info['description']}\n"
            base_roles_msg += "   ---\n"
        
        await self.send_text(base_roles_msg)
        
        # 扩展包角色
        if plugin.active_dlcs:
            dlc_roles_msg = "🎮 **扩展包角色列表**\n\n"
            for dlc_id, dlc in plugin.active_dlcs.items():
                dlc_roles_msg += f"📦 {dlc.dlc_name} (ID: {dlc_id})\n"
                for role_code, role_info in dlc.roles.items():
                    team_emoji = self._get_role_team_emoji(role_info["team"])
                    dlc_roles_msg += f"  {team_emoji} {role_info['name']} ({role_code})\n"
                    dlc_roles_msg += f"     阵营: {self._get_team_name(role_info['team'])}\n"
                    dlc_roles_msg += f"     类型: {'神民' if role_info.get('sub_role') else '普通'}\n"
                    if role_info.get('night_action'):
                        dlc_roles_msg += f"     夜晚行动: /wwg {role_info['action_command']}\n"
                    dlc_roles_msg += f"     描述: {role_info['description'][:50]}...\n"
                dlc_roles_msg += "  ---\n"
            
            await self.send_text(dlc_roles_msg)
        
        usage_msg = """
💡 **使用说明**
在房间设置中使用角色代号设置角色数量：
/wwg settings roles [角色代号] [数量]
例如：
/wwg settings roles seer 1
/wwg settings roles guard 1
/wwg settings roles hidden_wolf 1
"""
        await self.send_text(usage_msg)
        
        return True, "已显示所有角色", True

    def _get_role_team_emoji(self, team: str) -> str:
        """获取角色阵营表情"""
        team_emojis = {
            "village": "👨‍🌾",
            "werewolf": "🐺", 
            "neutral": "🎭"
        }
        return team_emojis.get(team, "❓")

    def _get_team_name(self, team: str) -> str:
        """获取阵营名称"""
        team_names = {
            "village": "村庄阵营",
            "werewolf": "狼人阵营",
            "neutral": "第三方阵营"
        }
        return team_names.get(team, "未知阵营")

    async def _handle_vote(self, user_id: str, game_data: Dict, params: str) -> bool:
        """处理投票"""
        if game_data["phase"] != "day":
            await self.send_text("❌ 现在不是投票时间。")
            return True

        if user_id not in game_data["alive_players"]:
            await self.send_text("❌ 您已出局，无法投票。")
            return True

        if params.strip().lower() == "skip":
            game_data["votes"][user_id] = "skip"
            await self.send_text("✅ 您已选择跳过投票。")
            await self._check_day_completion(game_data)
            return True

        try:
            target_num = int(params.strip())
            # 验证玩家号码
            alive_numbers = [game_data["players"][pid]["player_number"] for pid in game_data["alive_players"]]
            if target_num not in alive_numbers:
                await self.send_text("❌ 无效的玩家号码。")
                return True

            game_data["votes"][user_id] = target_num
            voter_num = game_data["players"][user_id]["player_number"]
            await self.send_text(f"✅ 玩家 {voter_num} 号投票给 {target_num} 号。")
            await self._check_day_completion(game_data)
            return True
        except ValueError:
            await self.send_text("❌ 投票格式错误。使用: /wwg vote [玩家号码] 或 /wwg vote skip")
            return True

    async def _handle_skip(self, user_id: str, game_data: Dict) -> bool:
        """处理跳过行动"""
        if game_data["phase"] == "night":
            if user_id in game_data.get("night_actions", {}):
                await self.send_text("❌ 您已经完成今晚的行动。")
                return True
            
            # 记录跳过夜晚行动
            if "night_actions" not in game_data:
                game_data["night_actions"] = {}
            game_data["night_actions"][user_id] = "skip"
            await self.send_text("✅ 您已跳过今晚的行动。")
            await self._check_night_completion(game_data)
            return True
        
        elif game_data["phase"] == "day":
            return await self._handle_vote(user_id, game_data, "skip")
        
        return False

    async def _handle_night_action(self, user_id: str, game_data: Dict, action: str, params: str) -> bool:
        """处理夜晚行动"""
        if game_data["phase"] != "night":
            await self.send_text("❌ 现在不是夜晚行动时间。")
            return True

        if user_id not in game_data["alive_players"]:
            await self.send_text("❌ 您已出局，无法行动。")
            return True

        player_role = game_data["players"][user_id]
        
        # 验证行动权限
        if not player_role.get("night_action") or player_role.get("action_command") != action:
            await self.send_text("❌ 您没有这个行动权限。")
            return True

        # 处理具体行动
        if action == "check":  # 预言家查验
            try:
                target_num = int(params.strip())
                target_player = self._get_player_by_number(game_data, target_num)
                if not target_player or target_player not in game_data["alive_players"]:
                    await self.send_text("❌ 无效的玩家号码。")
                    return True
                
                # 调用DLC修改器
                plugin = self.plugin_instance
                original_team = game_data["players"][target_player]["team"]
                original_result = "狼人阵营" if original_team == "werewolf" else "好人阵营"
                
                final_result = await plugin.call_dlc_modifier(
                    "modify_seer_result", game_data, original_result,
                    target_player=target_player, original_result=original_result
                )
                
                game_data.setdefault("night_actions", {})[user_id] = {
                    "type": "check",
                    "target": target_num,
                    "result": final_result
                }
                
                await self.send_text(f"🔮 查验结果: 玩家 {target_num} 号属于 {final_result}")
                await self._check_night_completion(game_data)
                return True
            except ValueError:
                await self.send_text("❌ 查验格式错误。使用: /wwg check [玩家号码]")
                return True

        elif action == "kill":  # 狼人杀人
            try:
                target_num = int(params.strip())
                target_player = self._get_player_by_number(game_data, target_num)
                if not target_player or target_player not in game_data["alive_players"]:
                    await self.send_text("❌ 无效的玩家号码。")
                    return True

                # 记录狼人投票
                if "wolf_votes" not in game_data:
                    game_data["wolf_votes"] = {}
                game_data["wolf_votes"][user_id] = target_num
                
                # 通知其他狼人
                wolf_teammates = self._get_wolf_teammates(game_data, user_id)
                for wolf_id in wolf_teammates:
                    if wolf_id != user_id:
                        try:
                            await send_api.text_to_user(
                                text=f"🐺 你的狼队友 {game_data['players'][user_id]['player_number']} 号投票要杀 {target_num} 号",
                                user_id=wolf_id,
                                platform="qq"
                            )
                        except:
                            pass
                
                await self.send_text(f"✅ 您投票要杀害玩家 {target_num} 号")
                await self._check_wolf_votes(game_data)
                return True
            except ValueError:
                await self.send_text("❌ 杀人格式错误。使用: /wwg kill [玩家号码]")
                return True

        elif action == "potion":  # 女巫用药
            params_list = params.split()
            if not params_list:
                await self.send_text("❌ 请选择行动。使用: /wwg potion [1/2] [玩家号码]")
                return True

            try:
                choice = int(params_list[0])
                if choice == 1 and player_role.get("has_antidote"):  # 使用解药
                    if len(params_list) < 2:
                        await self.send_text("❌ 请指定要救的玩家号码。")
                        return True
                    
                    target_num = int(params_list[1])
                    target_player = self._get_player_by_number(game_data, target_num)
                    if not target_player:
                        await self.send_text("❌ 无效的玩家号码。")
                        return True
                    
                    # 调用DLC修改器
                    plugin = self.plugin_instance
                    can_use_antidote = await plugin.call_dlc_modifier(
                        "modify_witch_antidote", game_data, True,
                        target_player=target_player
                    )
                    
                    if not can_use_antidote:
                        await self.send_text("❌ 解药对该玩家无效。")
                        return True
                    
                    game_data.setdefault("night_actions", {})[user_id] = {
                        "type": "antidote",
                        "target": target_num
                    }
                    player_role["has_antidote"] = False
                    await self.send_text(f"✅ 您使用解药救了玩家 {target_num} 号")
                    await self._check_night_completion(game_data)
                    return True

                elif choice == 2 and player_role.get("has_poison"):  # 使用毒药
                    if len(params_list) < 2:
                        await self.send_text("❌ 请指定要毒的玩家号码。")
                        return True
                    
                    target_num = int(params_list[1])
                    target_player = self._get_player_by_number(game_data, target_num)
                    if not target_player or target_player not in game_data["alive_players"]:
                        await self.send_text("❌ 无效的玩家号码。")
                        return True
                    
                    # 调用DLC修改器
                    plugin = self.plugin_instance
                    can_use_poison = await plugin.call_dlc_modifier(
                        "modify_witch_poison", game_data, True,
                        target_player=target_player
                    )
                    
                    if not can_use_poison:
                        await self.send_text("❌ 毒药对该玩家无效。")
                        return True
                    
                    game_data.setdefault("night_actions", {})[user_id] = {
                        "type": "poison",
                        "target": target_num
                    }
                    player_role["has_poison"] = False
                    await self.send_text(f"✅ 您使用毒药毒了玩家 {target_num} 号")
                    await self._check_night_completion(game_data)
                    return True

                else:
                    await self.send_text("❌ 无效的选择或没有相应的药水。")
                    return True

            except ValueError:
                await self.send_text("❌ 参数格式错误。使用: /wwg potion [1/2] [玩家号码]")
                return True

        return False

    async def _handle_revenge(self, user_id: str, game_data: Dict, params: str) -> bool:
        """处理猎人复仇"""
        if game_data["phase"] != "revenge":
            await self.send_text("❌ 现在不是复仇时间。")
            return True

        if user_id != game_data.get("revenge_player"):
            await self.send_text("❌ 您没有复仇权限。")
            return True

        try:
            target_num = int(params.strip())
            target_player = self._get_player_by_number(game_data, target_num)
            if not target_player or target_player not in game_data["alive_players"]:
                await self.send_text("❌ 无效的玩家号码。")
                return True

            # 执行复仇
            game_data["revenge_target"] = target_num
            await self.send_text(f"✅ 您选择枪杀玩家 {target_num} 号")
            await self._complete_revenge(game_data)
            return True
        except ValueError:
            await self.send_text("❌ 复仇格式错误。使用: /wwg revenge [玩家号码]")
            return True

    async def _handle_white_wolf_explode(self, user_id: str, game_data: Dict, params: str) -> bool:
        """处理白狼王自爆"""
        if game_data["phase"] != "day":
            await self.send_text("❌ 只能在白天自爆。")
            return True

        player_role = game_data["players"][user_id]
        if player_role.get("original_code") != "white_wolf_king":
            await self.send_text("❌ 您不是白狼王。")
            return True

        try:
            target_num = int(params.strip())
            target_player = self._get_player_by_number(game_data, target_num)
            if not target_player or target_player not in game_data["alive_players"]:
                await self.send_text("❌ 无效的玩家号码。")
                return True

            # 执行自爆
            await self._send_to_group(game_data, f"💥 白狼王自爆！带走了玩家 {target_num} 号")
            
            # 处决目标玩家
            await self._execute_player(game_data, target_player, "白狼王带走", user_id)
            
            # 处决白狼王
            await self._execute_player(game_data, user_id, "自爆", None)
            
            # 立即进入黑夜
            await self._start_night(game_data)
            return True
        except ValueError:
            await self.send_text("❌ 自爆格式错误。使用: /wwg explode [玩家号码]")
            return True

    async def _check_day_completion(self, game_data: Dict):
        """检查白天是否完成"""
        alive_players = game_data["alive_players"]
        votes = game_data.get("votes", {})
        
        # 所有存活玩家都投票或跳过了
        if len(votes) == len(alive_players):
            await self._resolve_day_votes(game_data)

    async def _check_night_completion(self, game_data: Dict):
        """检查夜晚是否完成"""
        alive_players = game_data["alive_players"]
        night_actions = game_data.get("night_actions", {})
        
        # 检查所有需要夜晚行动的玩家是否都行动了
        night_action_players = [pid for pid in alive_players 
                               if game_data["players"][pid].get("night_action")]
        
        if len(night_actions) >= len(night_action_players):
            await self._resolve_night_actions(game_data)

    async def _check_wolf_votes(self, game_data: Dict):
        """检查狼人投票是否完成"""
        wolf_players = [pid for pid in game_data["alive_players"] 
                       if game_data["players"][pid]["team"] == "werewolf"]
        wolf_votes = game_data.get("wolf_votes", {})
        
        if len(wolf_votes) == len(wolf_players):
            await self._resolve_wolf_kill(game_data)

    async def _resolve_wolf_kill(self, game_data: Dict):
        """处理狼人杀人结果"""
        wolf_votes = game_data.get("wolf_votes", {})
        vote_count = {}
        
        for target_num in wolf_votes.values():
            vote_count[target_num] = vote_count.get(target_num, 0) + 1
        
        if vote_count:
            # 选择票数最多的目标
            max_votes = max(vote_count.values())
            candidates = [num for num, count in vote_count.items() if count == max_votes]
            kill_target = random.choice(candidates) if len(candidates) > 1 else candidates[0]
            
            game_data["wolf_kill_target"] = kill_target
            game_data.setdefault("night_actions", {})["wolf_kill"] = kill_target
            
            # 通知女巫
            witch_player = self._find_witch_player(game_data)
            if witch_player:
                try:
                    await send_api.text_to_user(
                        text=f"⚠️ 狼人选择了杀害玩家 {kill_target} 号，请决定是否使用解药",
                        user_id=witch_player,
                        platform="qq"
                    )
                except:
                    pass

    async def _resolve_day_votes(self, game_data: Dict):
        """处理白天投票结果"""
        votes = game_data.get("votes", {})
        skip_votes = [v for v in votes.values() if v == "skip"]
        num_votes = [v for v in votes.values() if v != "skip"]
        
        if len(skip_votes) > len(num_votes):
            # 多数人选择跳过投票
            await self._send_to_group(game_data, "🗳️ 多数玩家选择跳过投票，无人出局。")
            await self._start_night(game_data)
            return
        
        # 统计票数
        vote_count = {}
        for target_num in num_votes:
            vote_count[target_num] = vote_count.get(target_num, 0) + 1
        
        if vote_count:
            max_votes = max(vote_count.values())
            candidates = [num for num, count in vote_count.items() if count == max_votes]
            
            if len(candidates) == 1:
                # 唯一最高票，该玩家出局
                executed_num = candidates[0]
                executed_player = self._get_player_by_number(game_data, executed_num)
                executed_role = game_data["players"][executed_player]
                
                await self._execute_player(game_data, executed_player, "投票处决", None)
                
                # 调用DLC玩家死亡钩子
                plugin = self.plugin_instance
                await plugin.call_dlc_hook(
                    "on_player_death", game_data,
                    dead_player=executed_player, reason="vote", killer=None
                )
                
                # 检查猎人技能
                if executed_role.get("special_action") == "revenge" and executed_role.get("can_revenge"):
                    await self._start_revenge_phase(game_data, executed_player)
                else:
                    await self._check_game_end(game_data)
            else:
                # 平票，无人出局
                await self._send_to_group(game_data, f"🗳️ 玩家 {', '.join(map(str, candidates))} 号平票，无人出局。")
                await self._start_night(game_data)

    async def _resolve_night_actions(self, game_data: Dict):
        """解析夜晚行动结果"""
        # 调用DLC夜晚开始钩子
        plugin = self.plugin_instance
        await plugin.call_dlc_hook("on_night_start", game_data)
        
        # 处理狼人杀人
        wolf_kill_target = game_data.get("wolf_kill_target")
        killed_players = []
        
        if wolf_kill_target:
            killed_player = self._get_player_by_number(game_data, wolf_kill_target)
            # 检查是否被女巫解救
            antidote_used = any(action.get("type") == "antidote" and action.get("target") == wolf_kill_target 
                              for action in game_data.get("night_actions", {}).values() 
                              if isinstance(action, dict))
            
            # 调用DLC修改器检查狼人杀人效果
            if not antidote_used and killed_player:
                can_kill = await plugin.call_dlc_modifier(
                    "modify_wolf_kill", game_data, True,
                    target_player=killed_player
                )
                
                if can_kill:
                    killed_players.append((killed_player, "狼人杀害", None))
        
        # 处理女巫毒药
        for action in game_data.get("night_actions", {}).values():
            if isinstance(action, dict) and action.get("type") == "poison":
                poisoned_player = self._get_player_by_number(game_data, action["target"])
                if poisoned_player:
                    killed_players.append((poisoned_player, "女巫毒杀", None))
        
        # 执行死亡
        for player, reason, killer in killed_players:
            await self._execute_player(game_data, player, reason, killer)
            # 调用DLC玩家死亡钩子
            await plugin.call_dlc_hook(
                "on_player_death", game_data,
                dead_player=player, reason=reason, killer=killer
            )
        
        # 通知夜晚结果
        if killed_players:
            killed_nums = [game_data["players"][p]["player_number"] for p, _, _ in killed_players]
            await self._send_to_group(game_data, f"🌙 夜晚结束，玩家 {', '.join(map(str, killed_nums))} 号死亡。")
        else:
            await self._send_to_group(game_data, "🌙 夜晚结束，平安夜。")
        
        # 检查游戏结束
        if not await self._check_game_end(game_data):
            await self._start_day(game_data)

    async def _execute_player(self, game_data: Dict, player_id: str, reason: str, killer: str):
        """处决玩家"""
        if player_id in game_data["alive_players"]:
            game_data["alive_players"].remove(player_id)
            player_data = game_data["players"][player_id]
            player_data["alive"] = False
            player_data["death_reason"] = reason
            player_data["killer"] = killer
            
            # 更新游戏记录
            await self._update_game_file(game_data)

    async def _start_revenge_phase(self, game_data: Dict, hunter_id: str):
        """开始猎人复仇阶段"""
        game_data["phase"] = "revenge"
        game_data["revenge_player"] = hunter_id
        
        hunter_num = game_data["players"][hunter_id]["player_number"]
        await self._send_to_group(game_data, f"🎯 玩家 {hunter_num} 号（猎人）发动技能，进入复仇时间！")
        
        try:
            await send_api.text_to_user(
                text="🔫 你被处决了！请选择一名玩家进行复仇。使用: /wwg revenge [玩家号码]",
                user_id=hunter_id,
                platform="qq"
            )
        except:
            pass

    async def _complete_revenge(self, game_data: Dict):
        """完成猎人复仇"""
        target_num = game_data.get("revenge_target")
        if target_num:
            target_player = self._get_player_by_number(game_data, target_num)
            if target_player:
                await self._execute_player(game_data, target_player, "猎人枪杀", game_data["revenge_player"])
                
                target_role = game_data["players"][target_player]
                await self._send_to_group(
                    game_data, 
                    f"🔫 猎人复仇！玩家 {target_num} 号（{target_role['name']}）被枪杀。"
                )
        
        # 清理复仇状态
        game_data["phase"] = "night"
        game_data.pop("revenge_player", None)
        game_data.pop("revenge_target", None)
        
        await self._check_game_end(game_data)

    async def _check_game_end(self, game_data: Dict) -> bool:
        """检查游戏是否结束"""
        alive_players = game_data["alive_players"]
        werewolf_count = len([pid for pid in alive_players 
                            if game_data["players"][pid]["team"] == "werewolf"])
        village_count = len([pid for pid in alive_players 
                           if game_data["players"][pid]["team"] == "village"])
        
        winner = None
        if werewolf_count == 0:
            winner = "village"
        elif werewolf_count >= village_count:
            winner = "werewolf"
        
        if winner:
            await self._end_game(game_data, winner)
            return True
        return False

    async def _end_game(self, game_data: Dict, winner: str):
        """结束游戏"""
        winner_name = "村庄阵营" if winner == "village" else "狼人阵营"
        
        # 发送游戏结果
        result_msg = f"🎉 **游戏结束！{winner_name} 胜利！**\n\n"
        result_msg += "👥 **玩家身份公布：**\n"
        
        for player_id, role_info in game_data["players"].items():
            status = "✅ 存活" if role_info.get("alive", True) else "❌ 死亡"
            death_info = f" ({role_info.get('death_reason', '')})" if not role_info.get("alive", True) else ""
            result_msg += f"{role_info['player_number']}号: {role_info['name']} - {status}{death_info}\n"
        
        await self._send_to_group(game_data, result_msg)
        
        # 调用DLC游戏结束钩子
        plugin = self.plugin_instance
        await plugin.call_dlc_hook("on_game_end", game_data, winner=winner)
        
        # 更新玩家档案
        await self._update_player_profiles(game_data, winner)
        
        # 归档游戏记录
        await plugin._archive_game(game_data, winner)
        
        # 清理状态
        room_id = game_data["room_id"]
        if room_id in rooms:
            del rooms[room_id]
        if room_id in active_games:
            del active_games[room_id]

    async def _start_night(self, game_data: Dict):
        """开始夜晚"""
        game_data["phase"] = "night"
        game_data["day_number"] += 1
        game_data["votes"] = {}
        game_data["night_actions"] = {}
        game_data["wolf_votes"] = {}
        game_data["wolf_kill_target"] = None
        
        # 调用DLC夜晚开始钩子
        plugin = self.plugin_instance
        await plugin.call_dlc_hook("on_night_start", game_data)
        
        await self._send_to_group(game_data, f"🌙 第 {game_data['day_number']} 夜开始！请有能力的玩家行动。")
        
        # 通知有夜晚行动的玩家
        for player_id in game_data["alive_players"]:
            role_info = game_data["players"][player_id]
            if role_info.get("night_action"):
                action_prompt = role_info.get("action_prompt", "请使用相应命令进行行动")
                try:
                    await send_api.text_to_user(
                        text=f"🌙 夜晚行动时间！{action_prompt}",
                        user_id=player_id,
                        platform="qq"
                    )
                except:
                    pass

    async def _start_day(self, game_data: Dict):
        """开始白天"""
        game_data["phase"] = "day"
        game_data["votes"] = {}
        
        # 调用DLC白天开始钩子
        plugin = self.plugin_instance
        await plugin.call_dlc_hook("on_day_start", game_data)
        
        await self._send_to_group(
            game_data, 
            f"☀️ 第 {game_data['day_number']} 天开始！请讨论并投票。使用 /wwg vote [号码] 或 /wwg vote skip"
        )
        
        # 显示存活玩家
        alive_nums = [game_data["players"][pid]["player_number"] for pid in game_data["alive_players"]]
        await self._send_to_group(game_data, f"👥 存活玩家: {', '.join(map(str, alive_nums))} 号")

    def _get_player_by_number(self, game_data: Dict, player_num: int) -> Optional[str]:
        """通过玩家号码获取玩家ID"""
        for player_id, role_info in game_data["players"].items():
            if role_info["player_number"] == player_num:
                return player_id
        return None

    def _get_wolf_teammates(self, game_data: Dict, wolf_id: str) -> List[str]:
        """获取狼队友"""
        return [pid for pid in game_data["alive_players"] 
                if game_data["players"][pid]["team"] == "werewolf" 
                and game_data["players"][pid].get("vote_action")]

    def _find_witch_player(self, game_data: Dict) -> Optional[str]:
        """寻找女巫玩家"""
        for player_id in game_data["alive_players"]:
            if game_data["players"][player_id].get("action_command") == "potion":
                return player_id
        return None

    async def _send_to_group(self, game_data: Dict, message: str):
        """发送消息到游戏群组"""
        group_id = game_data.get("group_id")
        if group_id and group_id != "private":
            try:
                await send_api.text_to_group(text=message, group_id=group_id, platform="qq")
            except:
                pass

    async def _show_help(self) -> Tuple[bool, str, bool]:
        """显示帮助信息"""
        help_text = """
🐺 **狼人杀游戏帮助** 🐺

**基础命令：**
🔸 `/wwg host` - 创建房间
🔸 `/wwg join [房间号]` - 加入房间
🔸 `/wwg settings [参数]` - 房间设置(房主)
🔸 `/wwg start` - 开始游戏(房主)
🔸 `/wwg profile [QQ号]` - 查看游戏档案
🔸 `/wwg archive [对局码]` - 查询对局记录
🔸 `/wwg list` - 查看可用房间
🔸 `/wwg dlc list` - 查看可用扩展包
🔸 `/wwg roles list` - 查看所有可用角色代号
**房间设置参数：**
🔹 `players [6-18]` - 设置玩家数量
🔹 `extends [扩展ID] [true/false]` - 启用/禁用扩展
🔹 `roles [角色代号] [数量]` - 设置角色数量
**游戏内命令：**
🔸 `/wwg vote [玩家号]` - 白天投票
🔸 `/wwg vote skip` - 跳过投票
🔸 `/wwg skip` - 跳过夜晚行动
🔸 `/wwg check [玩家号]` - 预言家查验
🔸 `/wwg kill [玩家号]` - 狼人杀人
🔸 `/wwg potion [1/2] [玩家号]` - 女巫用药(1解药 2毒药)
🔸 `/wwg revenge [玩家号]` - 猎人复仇
🔸 `/wwg explode [玩家号]` - 白狼王自爆
🔸 `/wwg status` - 查看游戏状态
**扩展包命令：**
🔸 `/wwg guard [玩家号]` - 守卫守护
🔸 `/wwg swap [号码1] [号码2]` - 魔术师交换
🔸 `/wwg reveal [玩家号]` - 通灵师查验
🔸 `/wwg disguise [玩家号]` - 画皮伪装
🔸 `/wwg couple [号码1] [号码2]` - 丘比特连接
**基础角色：**
🐺 狼人(wolf) - 每晚杀人
🔮 预言家(seer) - 每晚查验身份
🧪 女巫(witch) - 有解药和毒药
🎯 猎人(hunt) - 死亡时可开枪
👨‍🌾 村民(vil) - 没有特殊能力
        """
        await self.send_text(help_text)
        return True, "已发送帮助信息", True

    async def _create_room(self, user_id: str, group_id: str) -> Tuple[bool, str, bool]:
        """创建房间"""
        room_id = self._generate_room_id()
        rooms[room_id] = {
            "host": user_id,
            "group_id": group_id,
            "players": [user_id],
            "settings": {
                "player_count": 8,
                "enabled_dlcs": [],
                "roles": {"vil": 3, "seer": 1, "witch": 1, "hunt": 1, "wolf": 2}
            },
            "created_time": time.time(),
            "status": "waiting"
        }

        # 创建游戏记录文件
        game_file = self._create_game_file(room_id)
        
        await self.send_text(f"✅ 房间创建成功！\n🏠 房间号: {room_id}\n👥 当前玩家: 1/8\n使用 `/wwg join {room_id}` 加入游戏")
        return True, f"创建房间 {room_id}", True

    async def _join_room(self, user_id: str, group_id: str, params: str) -> Tuple[bool, str, bool]:
        """加入房间"""
        if not params:
            await self.send_text("❌ 请提供房间号。格式: /wwg join [房间号]")
            return False, "缺少房间号", True

        room_id = params.strip()
        if room_id not in rooms:
            await self.send_text("❌ 房间不存在或已过期。")
            return False, "房间不存在", True

        room = rooms[room_id]
        if user_id in room["players"]:
            await self.send_text("❌ 您已在房间中。")
            return False, "玩家已在房间", True

        if len(room["players"]) >= room["settings"]["player_count"]:
            await self.send_text("❌ 房间已满。")
            return False, "房间已满", True

        room["players"].append(user_id)
        await self.send_text(f"✅ 加入房间成功！\n👥 当前玩家: {len(room['players'])}/{room['settings']['player_count']}")
        return True, f"玩家 {user_id} 加入房间", True

    async def _room_settings(self, user_id: str, group_id: str, params: str) -> Tuple[bool, str, bool]:
        """房间设置"""
        # 查找用户所在的房间
        room_id = None
        for rid, room in rooms.items():
            if user_id in room["players"] and room["group_id"] == group_id:
                if room["host"] == user_id:
                    room_id = rid
                    break
        
        if not room_id:
            await self.send_text("❌ 您不是任何房间的房主。")
            return False, "不是房主", True

        room = rooms[room_id]
        if room["status"] != "waiting":
            await self.send_text("❌ 游戏已开始，无法修改设置。")
            return False, "游戏已开始", True

        params_list = params.split()
        if len(params_list) < 2:
            await self.send_text("❌ 设置参数格式错误。")
            return False, "参数格式错误", True

        setting_type = params_list[0].lower()
        
        if setting_type == "players":
            try:
                count = int(params_list[1])
                min_players = 6
                max_players = 18
                if count < min_players or count > max_players:
                    await self.send_text(f"❌ 玩家数量必须在{min_players}-{max_players}之间。")
                    return False, "玩家数量超出范围", True
                room["settings"]["player_count"] = count
                await self.send_text(f"✅ 设置玩家数量为: {count}")
            except ValueError:
                await self.send_text("❌ 玩家数量必须是数字。")
                return False, "玩家数量非数字", True

        elif setting_type == "extends":
            if len(params_list) < 3:
                await self.send_text("❌ 扩展设置格式: extends [扩展ID] [true/false]")
                return False, "扩展设置格式错误", True
            
            dlc_id = params_list[1].upper()
            enabled = params_list[2].lower() == "true"
            
            plugin = self.plugin_instance
            if dlc_id not in plugin.active_dlcs:
                await self.send_text("❌ 未知的扩展包ID。")
                return False, "未知扩展包", True
            
            if enabled:
                if dlc_id not in room["settings"]["enabled_dlcs"]:
                    room["settings"]["enabled_dlcs"].append(dlc_id)
                await self.send_text(f"✅ 已启用扩展包: {plugin.active_dlcs[dlc_id].dlc_name}")
            else:
                if dlc_id in room["settings"]["enabled_dlcs"]:
                    room["settings"]["enabled_dlcs"].remove(dlc_id)
                await self.send_text(f"✅ 已禁用扩展包: {plugin.active_dlcs[dlc_id].dlc_name}")

        elif setting_type == "roles":
            if len(params_list) < 3:
                await self.send_text("❌ 角色设置格式: roles [角色代号] [数量]")
                return False, "角色设置格式错误", True
            
            role_code = params_list[1].lower()
            try:
                count = int(params_list[2])
                
                # 检查基础角色
                if role_code in BASE_ROLES:
                    room["settings"]["roles"][role_code] = count
                    await self.send_text(f"✅ 设置 {BASE_ROLES[role_code]['name']} 数量为: {count}")
                else:
                    # 检查扩展包角色
                    plugin = self.plugin_instance
                    found = False
                    for dlc_id in room["settings"]["enabled_dlcs"]:
                        if dlc_id in plugin.active_dlcs:
                            dlc_roles = plugin.active_dlcs[dlc_id].roles
                            if role_code in dlc_roles:
                                room["settings"]["roles"][role_code] = count
                                await self.send_text(f"✅ 设置 {dlc_roles[role_code]['name']} 数量为: {count}")
                                found = True
                                break
                    
                    if not found:
                        await self.send_text("❌ 未知角色代号。使用 /wwg roles list 查看可用角色。")
                        return False, "未知角色", True
            except ValueError:
                await self.send_text("❌ 角色数量必须是数字。")
                return False, "角色数量非数字", True

        else:
            await self.send_text("❌ 未知设置类型。")
            return False, "未知设置类型", True

        return True, "设置已更新", True

    async def _start_game(self, user_id: str, group_id: str) -> Tuple[bool, str, bool]:
        """开始游戏"""
        room_id = None
        for rid, room in rooms.items():
            if user_id in room["players"] and room["group_id"] == group_id:
                if room["host"] == user_id:
                    room_id = rid
                    break
        
        if not room_id:
            await self.send_text("❌ 您不是任何房间的房主。")
            return False, "不是房主", True

        room = rooms[room_id]
        if len(room["players"]) < room["settings"]["player_count"]:
            await self.send_text(f"❌ 玩家不足。需要 {room['settings']['player_count']} 人，当前 {len(room['players'])} 人。")
            return False, "玩家不足", True

        # 分配角色并开始游戏
        success = await self._assign_roles_and_start(room_id)
        if success:
            await self.send_text("🎮 游戏开始！角色已分配，请查看私聊消息。")
            return True, "游戏开始", True
        else:
            await self.send_text("❌ 游戏启动失败，请重试。")
            return False, "游戏启动失败", True

    async def _assign_roles_and_start(self, room_id: str) -> bool:
        """分配角色并开始游戏"""
        room = rooms[room_id]
        players = room["players"]
        roles_config = room["settings"]["roles"]
        
        # 生成角色列表（包括基础角色和扩展角色）
        all_roles = BASE_ROLES.copy()
        plugin = self.plugin_instance
        
        # 添加启用的扩展包角色
        for dlc_id in room["settings"]["enabled_dlcs"]:
            if dlc_id in plugin.active_dlcs:
                all_roles.update(plugin.active_dlcs[dlc_id].roles)
        
        roles_list = []
        for role_code, count in roles_config.items():
            if role_code in all_roles:
                roles_list.extend([role_code] * count)
        
        if len(roles_list) != len(players):
            return False

        random.shuffle(roles_list)
        random.shuffle(players)

        # 分配角色
        game_data = {
            "room_id": room_id,
            "group_id": room["group_id"],
            "players": {},
            "phase": "night",
            "phase_start": time.time(),
            "day_number": 0,
            "alive_players": players.copy(),
            "votes": {},
            "actions": {},
            "game_start": time.time(),
            "settings": room["settings"]
        }

        for i, (player_id, role_code) in enumerate(zip(players, roles_list)):
            role_info = all_roles[role_code].copy()
            role_info["player_number"] = i + 1
            role_info["alive"] = True
            role_info["original_code"] = role_code  # 保存原始角色代码
            game_data["players"][player_id] = role_info

            # 发送私聊消息告知角色
            role_msg = self._format_role_message(role_info, players, i+1)
            try:
                await send_api.text_to_user(text=role_msg, user_id=player_id, platform="qq")
            except:
                pass

        active_games[room_id] = game_data
        room["status"] = "playing"
        room["game_start"] = time.time()

        # 调用DLC游戏开始钩子
        await plugin.call_dlc_hook("on_game_start", game_data)

        # 开始第一夜
        await self._start_night(game_data)
        return True

    def _format_role_message(self, role_info: Dict, players: List[str], player_num: int) -> str:
        """格式化角色信息消息"""
        role_name = role_info["name"]
        team = role_info["team"]
        description = role_info.get("description", "")
        
        message = f"🎮 **你的身份**\n\n"
        message += f"🔢 玩家号码: {player_num}\n"
        message += f"🎭 身份: {role_name}\n"
        message += f"🏴 阵营: {self._get_team_name(team)}\n"
        message += f"📖 描述: {description}\n"

        if team == "werewolf" and role_info.get("vote_action"):
            # 找到狼队友
            teammates = []
            # 注意：这里需要访问game_data，但在这个方法中不可用
            # 这个信息会在游戏开始后的私聊中单独发送
            pass

        if role_info.get("night_action"):
            message += f"\n🌙 夜晚行动命令: /wwg {role_info['action_command']} [目标]\n"

        if role_info.get("day_action"):
            message += f"\n☀️ 白天行动命令: /wwg {role_info['action_command']} [目标]\n"

        message += f"\n📖 使用 `/wwg 帮助` 查看游戏命令"

        return message

    def _generate_room_id(self) -> str:
        """生成房间ID"""
        timestamp = str(time.time())
        return hashlib.md5(timestamp.encode()).hexdigest()[:8]

    def _create_game_file(self, room_id: str) -> str:
        """创建游戏记录文件"""
        file_path = os.path.join(os.path.dirname(__file__), "games", f"{room_id}.json")
        try:
            game_data = {
                "room_id": room_id,
                "host": rooms[room_id]["host"],
                "start_time": datetime.datetime.now().isoformat(),
                "players": [],
                "status": "waiting",
                "events": []
            }
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(game_data, f, ensure_ascii=False, indent=2)
            return file_path
        except Exception as e:
            print(f"创建游戏文件失败: {e}")
            return ""

    async def _update_game_file(self, game_data: Dict):
        """更新游戏记录文件"""
        file_path = os.path.join(os.path.dirname(__file__), "games", f"{game_data['room_id']}.json")
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(game_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"更新游戏文件失败: {e}")

    async def _show_profile(self, user_id: str, params: str) -> Tuple[bool, str, bool]:
        """显示玩家档案"""
        target_id = params.strip() if params else user_id
        
        if target_id not in player_profiles:
            # 创建新档案
            player_profiles[target_id] = {
                "total_games": 0,
                "wins": 0,
                "losses": 0,
                "kills": 0,
                "votes": 0,
                "recent_win_rate": 0
            }
            await self._save_profile(target_id)

        profile = player_profiles[target_id]
        msg = f"📊 **玩家游戏档案**\n\n"
        msg += f"🎮 总对局数: {profile.get('total_games', 0)}\n"
        msg += f"✅ 胜利次数: {profile.get('wins', 0)}\n"
        msg += f"❌ 失败次数: {profile.get('losses', 0)}\n"
        msg += f"🎯 击杀人数: {profile.get('kills', 0)}\n"
        msg += f"🗳️ 票杀人数: {profile.get('votes', 0)}\n"
        
        if profile.get('total_games', 0) > 0:
            win_rate = (profile.get('wins', 0) / profile.get('total_games', 0)) * 100
            msg += f"📈 胜率: {win_rate:.1f}%\n"

        await self.send_text(msg)
        return True, "已显示玩家档案", True

    async def _show_archive(self, params: str) -> Tuple[bool, str, bool]:
        """显示对局记录"""
        if not params:
            await self.send_text("❌ 请提供对局码。格式: /wwg archive [对局码]")
            return False, "缺少对局码", True

        game_code = params.strip()
        if game_code not in game_archives:
            await self.send_text("❌ 未找到该对局记录。")
            return False, "对局记录不存在", True

        try:
            game_data = game_archives[game_code]
            msg = self._format_archive_message(game_data)
            await self.send_text(msg)
            return True, "已显示对局记录", True
        except Exception as e:
            await self.send_text("❌ 读取对局记录失败。")
            return False, "读取对局记录失败", True

    def _format_archive_message(self, game_data: Dict) -> str:
        """格式化对局记录消息"""
        msg = f"📜 **对局记录** {game_data.get('game_code', '')}\n\n"
        msg += f"🏠 房间号: {game_data.get('room_id', '')}\n"
        msg += f"⏰ 开始时间: {game_data.get('start_time', '')}\n"
        msg += f"🏁 结束时间: {game_data.get('end_time', '')}\n"
        msg += f"🎯 胜利阵营: {self._get_team_name(game_data.get('winner', ''))}\n\n"
        
        msg += "👥 **玩家信息**\n"
        for player in game_data.get('players', []):
            status = "✅ 存活" if player.get('alive', False) else "❌ 死亡"
            msg += f"{player.get('number', '')}号: {player.get('role', '')} - {status}\n"
            if not player.get('alive', False):
                msg += f"   死因: {player.get('death_reason', '')}\n"

        return msg

    async def _list_rooms(self) -> Tuple[bool, str, bool]:
        """列出可用房间"""
        if not rooms:
            await self.send_text("❌ 当前没有可用房间。")
            return False, "无可用房间", True

        msg = "🏠 **可用房间列表**\n\n"
        for room_id, room in rooms.items():
            if room["status"] == "waiting":
                msg += f"房间号: {room_id}\n"
                msg += f"玩家: {len(room['players'])}/{room['settings']['player_count']}\n"
                msg += f"房主: {room['host']}\n"
                msg += "---\n"

        await self.send_text(msg)
        return True, "已显示房间列表", True

    async def _show_game_status(self, game_data: Dict) -> bool:
        """显示游戏状态"""
        phase_name = "夜晚" if game_data["phase"] == "night" else "白天"
        alive_players = game_data["alive_players"]
        
        msg = f"🎮 **游戏状态**\n\n"
        msg += f"📅 第 {game_data['day_number']} {phase_name}\n"
        msg += f"👥 存活玩家: {len(alive_players)}人\n"
        msg += f"🔢 存活号码: {', '.join(str(game_data['players'][pid]['player_number']) for pid in alive_players)}\n"
        
        await self.send_text(msg)
        return True

    async def _update_player_profiles(self, game_data: Dict, winner: str):
        """更新玩家档案"""
        for player_id, role_info in game_data["players"].items():
            if player_id not in player_profiles:
                player_profiles[player_id] = {
                    "total_games": 0,
                    "wins": 0,
                    "losses": 0,
                    "kills": 0,
                    "votes": 0
                }
            
            profile = player_profiles[player_id]
            profile["total_games"] += 1
            
            # 判断胜负
            player_team = role_info["team"]
            if player_team == winner:
                profile["wins"] += 1
            else:
                profile["losses"] += 1
            
            await self._save_profile(player_id)

    async def _save_profile(self, player_id: str):
        """保存玩家档案"""
        file_path = os.path.join(os.path.dirname(__file__), "users", f"{player_id}.json")
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(player_profiles[player_id], f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存玩家档案失败: {e}")