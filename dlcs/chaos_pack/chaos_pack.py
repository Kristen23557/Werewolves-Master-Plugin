import random
from typing import Dict, List, Optional, Tuple, Any
from src.plugin_system.apis import send_api


class ChaosPackDLC:
    """混乱者包扩展包"""
    
    def __init__(self):
        self.dlc_id = "CH01"
        self.dlc_name = "混乱者包"
        self.author = "Assistant"
        self.version = "1.0.0"
        self.roles = self._initialize_roles()
    
    def _initialize_roles(self) -> Dict[str, Dict]:
        """初始化所有角色定义"""
        return {
            "hidden_wolf": {
                "name": "隐狼",
                "team": "werewolf",
                "sub_role": False,
                "night_action": False,
                "description": "潜伏在好人中的狼。被预言家查验时显示为好人。不能自爆，不能参与狼人夜间的杀人。当其他所有狼人队友出局后，隐狼获得刀人能力",
                "hidden_from_seer": True,
                "can_kill": False,
                "transforms_to_wolf": True
            },
            "guard": {
                "name": "守卫",
                "team": "village",
                "sub_role": True,
                "night_action": True,
                "action_command": "guard",
                "description": "每晚可以守护一名玩家（包括自己），使其免于狼人的袭击。不能连续两晚守护同一名玩家",
                "action_prompt": "请选择要守护的玩家号码",
                "last_guard_target": None
            },
            "magician": {
                "name": "魔术师",
                "team": "village",
                "sub_role": True,
                "night_action": True,
                "action_command": "swap",
                "description": "每晚可以选择交换两名玩家的号码牌，持续到下一个夜晚。当晚所有以他们为目标的技能效果都会被交换",
                "action_prompt": "请选择要交换的两个玩家号码 (格式: 号码1 号码2)",
                "swapped_players": None
            },
            "double_face": {
                "name": "双面人",
                "team": "neutral",
                "sub_role": False,
                "night_action": False,
                "description": "游戏开始时无固定阵营。被狼人击杀时加入狼人阵营，被投票放逐时加入好人阵营。女巫的毒药无效",
                "can_change_team": True,
                "immune_to_poison": True,
                "original_team": "neutral"
            },
            "spiritualist": {
                "name": "通灵师",
                "team": "village",
                "sub_role": True,
                "night_action": True,
                "action_command": "reveal",
                "description": "每晚可以查验一名玩家的具体身份。无法被守卫守护，且女巫的解药对其无效",
                "action_prompt": "请选择要查验具体身份的玩家号码",
                "cannot_be_guarded": True,
                "antidote_ineffective": True
            },
            "successor": {
                "name": "继承者",
                "team": "village",
                "sub_role": False,
                "night_action": False,
                "description": "当相邻的神民出局时，继承者会秘密获得该神民的技能，并晋升为神民",
                "can_inherit_skills": True,
                "inherited_skill": None
            },
            "skin_walker": {
                "name": "画皮",
                "team": "werewolf",
                "sub_role": False,
                "night_action": True,
                "action_command": "disguise",
                "description": "游戏第二夜起，可以潜入一名已出局玩家的身份，之后被预言家查验时会显示为该身份",
                "action_prompt": "请选择要伪装的已出局玩家号码",
                "can_disguise": True,
                "disguise_used": False,
                "disguised_as": None
            },
            "white_wolf_king": {
                "name": "白狼王",
                "team": "werewolf",
                "sub_role": False,
                "night_action": False,
                "day_action": True,
                "action_command": "explode",
                "description": "白天投票放逐阶段，可以随时翻牌自爆，并带走一名玩家。此行动会立即终止当天发言并进入黑夜",
                "action_prompt": "请选择要带走的玩家号码",
                "can_explode": True
            },
            "cupid": {
                "name": "丘比特",
                "team": "neutral",
                "sub_role": False,
                "night_action": True,
                "action_command": "couple",
                "description": "游戏第一晚，选择两名玩家成为情侣。丘比特与情侣形成第三方阵营。情侣中若有一方死亡，另一方会立即殉情",
                "action_prompt": "请选择要结成情侣的两个玩家号码 (格式: 号码1 号码2)",
                "first_night_only": True,
                "couples": None
            }
        }
    
    # === 核心钩子方法 ===
    
    async def on_game_start(self, game_data: Dict) -> None:
        """游戏开始时初始化扩展包数据"""
        self._ensure_dlc_data(game_data)
        self._initialize_role_data(game_data)
    
    async def on_night_start(self, game_data: Dict) -> None:
        """夜晚开始时的处理"""
        if not self._has_dlc_data(game_data):
            return
            
        dlc_data = self._get_dlc_data(game_data)
        dlc_data.update({
            "swapped_players": None,
            "guarded_players": {}
        })
        
        await self._check_hidden_wolf_transform(game_data)
        await self._check_successor_inheritance(game_data)
    
    async def on_day_start(self, game_data: Dict) -> None:
        """白天开始时的处理"""
        # 可在此处添加白天重置逻辑
        pass
    
    async def on_player_death(self, game_data: Dict, dead_player: str, reason: str, killer: str) -> None:
        """玩家死亡时的处理"""
        if not self._has_dlc_data(game_data):
            return
            
        await self._handle_lover_suicide(game_data, dead_player, reason)
        await self._handle_double_face_conversion(game_data, dead_player, reason)
        await self._handle_successor_adjacent_death(game_data, dead_player)
    
    async def on_game_end(self, game_data: Dict, winner: str) -> None:
        """游戏结束时的处理"""
        if self._has_dlc_data(game_data):
            game_data["dlc_data"]["chaos_pack"].clear()
    
    async def handle_command(self, user_id: str, game_data: Dict, action: str, params: str) -> bool:
        """处理扩展包专属命令"""
        if not self._is_valid_player(user_id, game_data):
            return False
            
        role_code = game_data["players"][user_id].get("original_code")
        command_handlers = {
            "guard": ("guard", self._handle_guard_action),
            "swap": ("magician", self._handle_swap_action),
            "reveal": ("spiritualist", self._handle_reveal_action),
            "disguise": ("skin_walker", self._handle_disguise_action),
            "couple": ("cupid", self._handle_couple_action)
        }
        
        if action in command_handlers:
            required_role, handler = command_handlers[action]
            if role_code == required_role:
                return await handler(user_id, game_data, params)
        
        return False
    
    # === 修改器方法 ===
    
    async def modify_seer_result(self, game_data: Dict, original_result: str, **kwargs) -> str:
        """修改预言家查验结果"""
        target_player = kwargs.get('target_player')
        if not target_player or not self._has_dlc_data(game_data):
            return original_result
            
        target_role = game_data["players"][target_player]
        
        # 隐狼显示为好人
        if self._is_hidden_wolf(target_role):
            return "好人阵营"
        
        # 画皮显示为伪装身份
        if self._is_disguised_skin_walker(target_role):
            return f"好人阵营 ({target_role['disguised_as']})"
        
        # 处理魔术师交换
        swapped_result = await self._apply_swapped_seer_result(game_data, target_role)
        if swapped_result:
            return swapped_result
        
        return original_result
    
    async def modify_wolf_kill(self, game_data: Dict, default_value: bool, **kwargs) -> bool:
        """修改狼人杀人效果"""
        target_player = kwargs.get('target_player')
        if not target_player or not self._has_dlc_data(game_data):
            return default_value
            
        # 检查守卫守护
        if self._is_guarded(game_data, target_player):
            return False
        
        # 处理魔术师交换
        effective_player = await self._get_swapped_target(game_data, target_player)
        if effective_player != target_player:
            # 检查交换后目标的守护状态
            if self._is_guarded(game_data, effective_player):
                return False
        
        # 标记双面人转换
        target_role = game_data["players"][target_player]
        if self._is_double_face(target_role):
            target_role["death_trigger"] = "wolf_kill"
        
        return default_value
    
    async def modify_guard_protect(self, game_data: Dict, default_value: bool, **kwargs) -> bool:
        """修改守卫守护效果"""
        target_player = kwargs.get('target_player')
        if not target_player:
            return default_value
            
        target_role = game_data["players"][target_player]
        return default_value and not self._is_spiritualist(target_role)
    
    async def modify_witch_antidote(self, game_data: Dict, default_value: bool, **kwargs) -> bool:
        """修改女巫解药效果"""
        target_player = kwargs.get('target_player')
        if not target_player:
            return default_value
            
        target_role = game_data["players"][target_player]
        return default_value and not self._is_spiritualist(target_role)
    
    async def modify_witch_poison(self, game_data: Dict, default_value: bool, **kwargs) -> bool:
        """修改女巫毒药效果"""
        target_player = kwargs.get('target_player')
        if not target_player:
            return default_value
            
        target_role = game_data["players"][target_player]
        return default_value and not self._is_double_face(target_role)
    
    # === 角色行动处理 ===
    
    async def _handle_guard_action(self, user_id: str, game_data: Dict, params: str) -> bool:
        """处理守卫守护"""
        try:
            target_num = int(params.strip())
            if not await self._validate_guard_action(user_id, game_data, target_num):
                return True
                
            # 记录行动
            self._record_night_action(game_data, user_id, "guard", {"target": target_num})
            game_data["players"][user_id]["last_guard_target"] = target_num
            
            # 更新DLC数据
            target_player = self._get_player_by_number(game_data, target_num)
            dlc_data = self._get_dlc_data(game_data)
            dlc_data.setdefault("guarded_players", {})[target_player] = user_id
            
            await self._send_user_message(user_id, f"✅ 您选择守护玩家 {target_num} 号")
            return True
            
        except ValueError:
            await self._send_user_message(user_id, "❌ 守护格式错误。使用: /wwg guard [玩家号码]")
            return True
    
    async def _handle_swap_action(self, user_id: str, game_data: Dict, params: str) -> bool:
        """处理魔术师交换"""
        try:
            num1, num2 = self._parse_two_numbers(params)
            if not await self._validate_swap_action(user_id, game_data, num1, num2):
                return True
                
            # 记录行动
            self._record_night_action(game_data, user_id, "swap", {"targets": [num1, num2]})
            
            # 更新DLC数据
            dlc_data = self._get_dlc_data(game_data)
            dlc_data["swapped_players"] = [num1, num2]
            
            await self._send_user_message(user_id, f"✅ 您交换了玩家 {num1} 号和 {num2} 号的号码牌")
            return True
            
        except ValueError:
            await self._send_user_message(user_id, "❌ 交换格式错误。使用: /wwg swap [号码1] [号码2]")
            return True
    
    async def _handle_reveal_action(self, user_id: str, game_data: Dict, params: str) -> bool:
        """处理通灵师查验"""
        try:
            target_num = int(params.strip())
            target_player = self._get_player_by_number(game_data, target_num)
            if not target_player or target_player not in game_data["alive_players"]:
                await self._send_user_message(user_id, "❌ 无效的玩家号码。")
                return True
            
            role_name = game_data["players"][target_player]["name"]
            self._record_night_action(game_data, user_id, "reveal", {
                "target": target_num,
                "result": role_name
            })
            
            await self._send_user_message(user_id, f"🔮 查验结果: 玩家 {target_num} 号是 {role_name}")
            return True
            
        except ValueError:
            await self._send_user_message(user_id, "❌ 查验格式错误。使用: /wwg reveal [玩家号码]")
            return True
    
    async def _handle_disguise_action(self, user_id: str, game_data: Dict, params: str) -> bool:
        """处理画皮伪装"""
        try:
            target_num = int(params.strip())
            if not await self._validate_disguise_action(user_id, game_data, target_num):
                return True
                
            target_player = self._get_player_by_number(game_data, target_num)
            target_role = game_data["players"][target_player]
            
            # 记录行动
            self._record_night_action(game_data, user_id, "disguise", {
                "target": target_num,
                "disguise_as": target_role["name"]
            })
            
            # 更新玩家状态
            player_role = game_data["players"][user_id]
            player_role.update({
                "disguise_used": True,
                "disguised_as": target_role["name"]
            })
            
            # 更新DLC数据
            dlc_data = self._get_dlc_data(game_data)
            dlc_data.setdefault("disguised_players", {})[user_id] = target_role["name"]
            
            await self._send_user_message(user_id, f"✅ 您伪装成了 {target_role['name']}")
            return True
            
        except ValueError:
            await self._send_user_message(user_id, "❌ 伪装格式错误。使用: /wwg disguise [已出局玩家号码]")
            return True
    
    async def _handle_couple_action(self, user_id: str, game_data: Dict, params: str) -> bool:
        """处理丘比特连接情侣"""
        try:
            num1, num2 = self._parse_two_numbers(params)
            if not await self._validate_couple_action(user_id, game_data, num1, num2):
                return True
                
            player1 = self._get_player_by_number(game_data, num1)
            player2 = self._get_player_by_number(game_data, num2)
            
            # 记录行动
            self._record_night_action(game_data, user_id, "couple", {"targets": [num1, num2]})
            
            # 创建情侣关系
            self._create_lover_relationship(game_data, user_id, player1, player2)
            
            await self._send_user_message(user_id, f"✅ 您将玩家 {num1} 号和 {num2} 号结为情侣")
            await self._notify_lovers(game_data, player1, player2, num1, num2)
            return True
            
        except ValueError:
            await self._send_user_message(user_id, "❌ 连接格式错误。使用: /wwg couple [号码1] [号码2]")
            return True
    
    # === 验证方法 ===
    
    async def _validate_guard_action(self, user_id: str, game_data: Dict, target_num: int) -> bool:
        """验证守卫行动"""
        target_player = self._get_player_by_number(game_data, target_num)
        if not target_player or target_player not in game_data["alive_players"]:
            await self._send_user_message(user_id, "❌ 无效的玩家号码。")
            return False
        
        player_role = game_data["players"][user_id]
        if player_role.get("last_guard_target") == target_num:
            await self._send_user_message(user_id, "❌ 不能连续两晚守护同一名玩家。")
            return False
        
        can_guard = await self.modify_guard_protect(game_data, True, target_player=target_player)
        if not can_guard:
            await self._send_user_message(user_id, "❌ 无法守护该玩家。")
            return False
            
        return True
    
    async def _validate_swap_action(self, user_id: str, game_data: Dict, num1: int, num2: int) -> bool:
        """验证交换行动"""
        player1 = self._get_player_by_number(game_data, num1)
        player2 = self._get_player_by_number(game_data, num2)
        
        if not player1 or not player2 or num1 == num2:
            await self._send_user_message(user_id, "❌ 无效的玩家号码。")
            return False
            
        return True
    
    async def _validate_disguise_action(self, user_id: str, game_data: Dict, target_num: int) -> bool:
        """验证伪装行动"""
        target_player = self._get_player_by_number(game_data, target_num)
        if not target_player or target_player in game_data["alive_players"]:
            await self._send_user_message(user_id, "❌ 只能选择已出局的玩家。")
            return False
        
        player_role = game_data["players"][user_id]
        if player_role.get("disguise_used", False):
            await self._send_user_message(user_id, "❌ 本局游戏已经使用过伪装能力。")
            return False
        
        if game_data["day_number"] < 1:
            await self._send_user_message(user_id, "❌ 第二夜起才能使用伪装能力。")
            return False
            
        return True
    
    async def _validate_couple_action(self, user_id: str, game_data: Dict, num1: int, num2: int) -> bool:
        """验证情侣连接行动"""
        player1 = self._get_player_by_number(game_data, num1)
        player2 = self._get_player_by_number(game_data, num2)
        
        if not player1 or not player2 or num1 == num2:
            await self._send_user_message(user_id, "❌ 无效的玩家号码。")
            return False
        
        if game_data["day_number"] > 0:
            await self._send_user_message(user_id, "❌ 只能在第一夜连接情侣。")
            return False
            
        return True
    
    # === 特殊效果处理 ===
    
    async def _check_hidden_wolf_transform(self, game_data: Dict):
        """检查隐狼变身"""
        for player_id, role_info in game_data["players"].items():
            if (self._is_hidden_wolf(role_info) and 
                role_info.get("alive") and 
                not role_info.get("can_kill")):
                
                other_wolves = self._get_other_wolves(game_data, player_id)
                if not other_wolves:
                    self._transform_hidden_wolf(role_info)
                    await self._send_user_message(player_id, 
                        "🐺 你的狼队友全部出局，你获得了刀人能力！现在可以使用 /wwg kill 命令")
    
    async def _check_successor_inheritance(self, game_data: Dict):
        """检查继承者技能继承"""
        for player_id, role_info in game_data["players"].items():
            if (self._is_successor(role_info) and 
                role_info.get("alive") and 
                not role_info.get("inherited_skill")):
                
                inherited_skill = self._find_adjacent_sub_role_skill(game_data, role_info["player_number"])
                if inherited_skill:
                    self._inherit_skill(role_info, inherited_skill)
                    dlc_data = self._get_dlc_data(game_data)
                    dlc_data.setdefault("inherited_skills", {})[player_id] = inherited_skill["code"]
                    
                    await self._send_user_message(player_id,
                        f"🎯 你继承了 {inherited_skill['name']} 的能力！现在可以使用 /wwg {inherited_skill.get('action_command', '')} 命令")
    
    async def _handle_lover_suicide(self, game_data: Dict, dead_player: str, reason: str):
        """处理情侣殉情"""
        dlc_data = self._get_dlc_data(game_data)
        lovers = dlc_data.get("lovers", [])
        
        if dead_player in lovers:
            other_lover = next((lid for lid in lovers if lid != dead_player), None)
            if other_lover and game_data["players"][other_lover].get("alive"):
                other_num = game_data["players"][other_lover]["player_number"]
                await self._send_group_message(game_data, f"💔 玩家 {other_num} 号因情侣死亡而殉情")
                game_data["players"][other_lover]["death_trigger"] = "suicide"
    
    async def _handle_double_face_conversion(self, game_data: Dict, dead_player: str, reason: str):
        """处理双面人阵营转换"""
        dead_role = game_data["players"][dead_player]
        
        if self._is_double_face(dead_role) and dead_role.get("alive"):
            new_team = "werewolf" if reason == "wolf_kill" else "village" if reason == "vote" else None
            if new_team:
                dead_role.update({
                    "team": new_team,
                    "death_trigger": "converted"
                })
                
                team_name = "狼人" if new_team == "werewolf" else "村庄"
                await self._send_user_message(dead_player, f"🐺 你被{'狼人袭击' if new_team == 'werewolf' else '投票放逐'}，现在加入了{team_name}阵营！")
                
                dlc_data = self._get_dlc_data(game_data)
                dlc_data.setdefault("double_face_conversions", {})[dead_player] = new_team
    
    async def _handle_successor_adjacent_death(self, game_data: Dict, dead_player: str):
        """处理继承者相邻神民死亡"""
        # 触发继承检查（在夜晚开始时处理）
        pass
    
    # === 辅助方法 ===
    
    def _ensure_dlc_data(self, game_data: Dict) -> None:
        """确保DLC数据存在"""
        if "dlc_data" not in game_data:
            game_data["dlc_data"] = {}
        if "chaos_pack" not in game_data["dlc_data"]:
            game_data["dlc_data"]["chaos_pack"] = {
                "swapped_players": None,
                "lovers": [],
                "cupid": None,
                "guarded_players": {},
                "disguised_players": {},
                "double_face_conversions": {},
                "inherited_skills": {}
            }
    
    def _has_dlc_data(self, game_data: Dict) -> bool:
        """检查DLC数据是否存在"""
        return "dlc_data" in game_data and "chaos_pack" in game_data["dlc_data"]
    
    def _get_dlc_data(self, game_data: Dict) -> Dict:
        """获取DLC数据"""
        return game_data["dlc_data"]["chaos_pack"]
    
    def _initialize_role_data(self, game_data: Dict) -> None:
        """初始化角色数据"""
        for player_id, role_info in game_data["players"].items():
            role_code = role_info.get("original_code")
            if role_code in self.roles:
                base_role = self.roles[role_code]
                # 只添加不存在的属性
                for key, value in base_role.items():
                    if key not in role_info:
                        role_info[key] = value
    
    def _is_valid_player(self, user_id: str, game_data: Dict) -> bool:
        """检查玩家是否有效"""
        return user_id in game_data.get("players", {})
    
    def _get_player_by_number(self, game_data: Dict, player_num: int) -> Optional[str]:
        """通过玩家号码获取玩家ID"""
        for player_id, role_info in game_data["players"].items():
            if role_info["player_number"] == player_num:
                return player_id
        return None
    
    def _parse_two_numbers(self, params: str) -> Tuple[int, int]:
        """解析两个数字参数"""
        parts = params.split()
        if len(parts) != 2:
            raise ValueError("需要两个参数")
        return int(parts[0]), int(parts[1])
    
    def _record_night_action(self, game_data: Dict, user_id: str, action_type: str, data: Dict) -> None:
        """记录夜晚行动"""
        game_data.setdefault("night_actions", {})[user_id] = {
            "type": action_type,
            **data
        }
    
    async def _send_user_message(self, user_id: str, message: str) -> None:
        """发送用户消息"""
        try:
            await send_api.text_to_user(text=message, user_id=user_id, platform="qq")
        except:
            pass
    
    async def _send_group_message(self, game_data: Dict, message: str) -> None:
        """发送群组消息"""
        group_id = game_data.get("group_id")
        if group_id and group_id != "private":
            try:
                await send_api.text_to_group(text=message, group_id=group_id, platform="qq")
            except:
                pass
    
    async def _notify_lovers(self, game_data: Dict, player1: str, player2: str, num1: int, num2: int) -> None:
        """通知情侣"""
        lover1_num = num2 if num1 == game_data["players"][player1]["player_number"] else num1
        lover2_num = num1 if num2 == game_data["players"][player2]["player_number"] else num2
        
        await self._send_user_message(player1, f"💕 你被丘比特选中成为情侣！你的情侣是玩家 {lover1_num} 号")
        await self._send_user_message(player2, f"💕 你被丘比特选中成为情侣！你的情侣是玩家 {lover2_num} 号")
    
    def _create_lover_relationship(self, game_data: Dict, cupid_id: str, player1: str, player2: str) -> None:
        """创建情侣关系"""
        dlc_data = self._get_dlc_data(game_data)
        dlc_data.update({
            "lovers": [player1, player2],
            "cupid": cupid_id
        })
        
        # 设置情侣标记
        for player_id in [player1, player2, cupid_id]:
            game_data["players"][player_id]["lover"] = True
    
    # === 角色类型检查 ===
    
    def _is_hidden_wolf(self, role_info: Dict) -> bool:
        """检查是否为隐狼"""
        return (role_info.get("original_code") == "hidden_wolf" and 
                role_info.get("hidden_from_seer"))
    
    def _is_disguised_skin_walker(self, role_info: Dict) -> bool:
        """检查是否为伪装的画皮"""
        return (role_info.get("original_code") == "skin_walker" and 
                role_info.get("disguised_as"))
    
    def _is_double_face(self, role_info: Dict) -> bool:
        """检查是否为双面人"""
        return role_info.get("original_code") == "double_face"
    
    def _is_spiritualist(self, role_info: Dict) -> bool:
        """检查是否为通灵师"""
        return (role_info.get("original_code") == "spiritualist" and 
                role_info.get("cannot_be_guarded"))
    
    def _is_successor(self, role_info: Dict) -> bool:
        """检查是否为继承者"""
        return role_info.get("original_code") == "successor"
    
    def _is_guarded(self, game_data: Dict, player_id: str) -> bool:
        """检查玩家是否被守护"""
        if not self._has_dlc_data(game_data):
            return False
        dlc_data = self._get_dlc_data(game_data)
        return player_id in dlc_data.get("guarded_players", {})
    
    # === 特殊效果应用 ===
    
    async def _apply_swapped_seer_result(self, game_data: Dict, target_role: Dict) -> Optional[str]:
        """应用交换后的预言家结果"""
        dlc_data = self._get_dlc_data(game_data)
        swapped_players = dlc_data.get("swapped_players")
        
        if swapped_players:
            target_num = target_role["player_number"]
            if target_num in swapped_players:
                idx = swapped_players.index(target_num)
                other_num = swapped_players[1 - idx]
                other_player = self._get_player_by_number(game_data, other_num)
                if other_player:
                    other_team = game_data["players"][other_player]["team"]
                    return "狼人阵营" if other_team == "werewolf" else "好人阵营"
        return None
    
    async def _get_swapped_target(self, game_data: Dict, original_player: str) -> str:
        """获取交换后的目标玩家"""
        dlc_data = self._get_dlc_data(game_data)
        swapped_players = dlc_data.get("swapped_players")
        
        if swapped_players:
            original_num = game_data["players"][original_player]["player_number"]
            if original_num in swapped_players:
                idx = swapped_players.index(original_num)
                other_num = swapped_players[1 - idx]
                other_player = self._get_player_by_number(game_data, other_num)
                if other_player:
                    return other_player
        return original_player
    
    def _get_other_wolves(self, game_data: Dict, exclude_player: str) -> List[str]:
        """获取其他狼人玩家"""
        return [pid for pid in game_data["alive_players"] 
                if pid != exclude_player and 
                game_data["players"][pid].get("team") == "werewolf" and
                game_data["players"][pid].get("original_code") != "hidden_wolf"]
    
    def _transform_hidden_wolf(self, role_info: Dict) -> None:
        """转换隐狼为普通狼人"""
        role_info.update({
            "can_kill": True,
            "night_action": True,
            "action_command": "kill"
        })
    
    def _find_adjacent_sub_role_skill(self, game_data: Dict, player_num: int) -> Optional[Dict]:
        """查找相邻神民的技能"""
        total_players = len(game_data["players"])
        adjacent_players = []
        
        if player_num > 1:
            left_player = self._get_player_by_number(game_data, player_num - 1)
            if left_player:
                adjacent_players.append(left_player)
        if player_num < total_players:
            right_player = self._get_player_by_number(game_data, player_num + 1)
            if right_player:
                adjacent_players.append(right_player)
        
        for adj_player in adjacent_players:
            adj_role = game_data["players"][adj_player]
            if (not adj_role.get("alive") and 
                adj_role.get("team") == "village" and 
                adj_role.get("sub_role")):
                return adj_role
        return None
    
    def _inherit_skill(self, role_info: Dict, inherited_role: Dict) -> None:
        """继承技能"""
        role_info.update({
            "inherited_skill": inherited_role.get("original_code"),
            "sub_role": True,
            "night_action": inherited_role.get("night_action"),
            "action_command": inherited_role.get("action_command"),
            "name": f"继承者({inherited_role['name']})"
        })


# 导出扩展包实例
chaos_pack = ChaosPackDLC()