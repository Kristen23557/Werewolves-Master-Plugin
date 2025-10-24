import random
from typing import Dict, List, Optional, Tuple
from src.plugin_system.apis import send_api

class ChaosPackDLC:
    """混乱者包扩展包"""
    
    def __init__(self):
        self.dlc_id = "CH01"
        self.dlc_name = "混乱者包"
        self.author = "Assistant"
        self.version = "1.0.0"
        self.roles = {
            "hidden_wolf": {
                "code": "hidden_wolf",
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
                "code": "guard",
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
                "code": "magician",
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
                "code": "double_face",
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
                "code": "spiritualist",
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
                "code": "successor",
                "name": "继承者",
                "team": "village",
                "sub_role": False,
                "night_action": False,
                "description": "当相邻的神民出局时，继承者会秘密获得该神民的技能，并晋升为神民",
                "can_inherit_skills": True,
                "inherited_skill": None
            },
            "skin_walker": {
                "code": "skin_walker",
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
                "code": "white_wolf_king",
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
                "code": "cupid",
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

    async def on_game_start(self, game_data: Dict) -> None:
        """游戏开始时初始化扩展包数据"""
        game_data["dlc_data"] = {
            "chaos_pack": {
                "swapped_players": None,
                "lovers": [],
                "cupid": None,
                "guarded_players": {},
                "disguised_players": {},
                "double_face_conversions": {},
                "inherited_skills": {}
            }
        }
        
        # 初始化扩展角色数据
        for player_id, role_info in game_data["players"].items():
            if role_info.get("original_code") in self.roles:
                role_data = self.roles[role_info["original_code"]].copy()
                role_info.update(role_data)

    async def on_night_start(self, game_data: Dict) -> None:
        """夜晚开始时的处理"""
        dlc_data = game_data["dlc_data"]["chaos_pack"]
        dlc_data["swapped_players"] = None  # 重置魔术师交换
        dlc_data["guarded_players"] = {}  # 重置守卫守护
        
        # 检查隐狼变身
        await self._check_hidden_wolf_transform(game_data)
        
        # 检查继承者技能继承
        await self._check_successor_inheritance(game_data)

    async def on_day_start(self, game_data: Dict) -> None:
        """白天开始时的处理"""
        # 重置一些每日状态
        pass

    async def on_player_death(self, game_data: Dict, dead_player: str, reason: str, killer: str) -> None:
        """玩家死亡时的处理"""
        # 处理情侣殉情
        await self._handle_lover_suicide(game_data, dead_player, reason)
        
        # 处理双面人阵营转换
        await self._handle_double_face_conversion(game_data, dead_player, reason)
        
        # 处理继承者相邻神民死亡
        await self._handle_successor_adjacent_death(game_data, dead_player)

    async def on_game_end(self, game_data: Dict, winner: str) -> None:
        """游戏结束时的处理"""
        # 清理扩展包数据
        if "dlc_data" in game_data and "chaos_pack" in game_data["dlc_data"]:
            game_data["dlc_data"]["chaos_pack"].clear()

    async def handle_command(self, user_id: str, game_data: Dict, action: str, params: str) -> bool:
        """处理扩展包专属命令"""
        player_role = game_data["players"][user_id]
        role_code = player_role.get("original_code")
        
        if action == "guard" and role_code == "guard":
            return await self._handle_guard_action(user_id, game_data, params)
        elif action == "swap" and role_code == "magician":
            return await self._handle_swap_action(user_id, game_data, params)
        elif action == "reveal" and role_code == "spiritualist":
            return await self._handle_reveal_action(user_id, game_data, params)
        elif action == "disguise" and role_code == "skin_walker":
            return await self._handle_disguise_action(user_id, game_data, params)
        elif action == "couple" and role_code == "cupid":
            return await self._handle_couple_action(user_id, game_data, params)
        
        return False

    async def modify_seer_result(self, game_data: Dict, original_result: str, **kwargs) -> str:
        """修改预言家查验结果"""
        target_player = kwargs.get('target_player')
        if not target_player:
            return original_result
            
        target_role = game_data["players"][target_player]
        dlc_data = game_data["dlc_data"]["chaos_pack"]
        
        # 隐狼显示为好人
        if (target_role.get("original_code") == "hidden_wolf" and 
            target_role.get("hidden_from_seer")):
            return "好人阵营"
        
        # 画皮显示为伪装身份
        if (target_role.get("original_code") == "skin_walker" and 
            target_role.get("disguised_as")):
            return f"好人阵营 ({target_role['disguised_as']})"
        
        # 处理魔术师交换
        swapped_players = dlc_data.get("swapped_players")
        if swapped_players:
            target_num = target_role["player_number"]
            if target_num in swapped_players:
                # 找到交换后的目标
                idx = swapped_players.index(target_num)
                other_idx = 1 - idx  # 0->1, 1->0
                other_num = swapped_players[other_idx]
                other_player = self._get_player_by_number(game_data, other_num)
                if other_player:
                    other_role = game_data["players"][other_player]
                    other_team = other_role["team"]
                    return "狼人阵营" if other_team == "werewolf" else "好人阵营"
        
        return original_result

    async def modify_wolf_kill(self, game_data: Dict, default_value: bool, **kwargs) -> bool:
        """修改狼人杀人效果"""
        target_player = kwargs.get('target_player')
        if not target_player:
            return default_value
            
        target_role = game_data["players"][target_player]
        dlc_data = game_data["dlc_data"]["chaos_pack"]
        
        # 检查是否被守卫守护
        if target_player in dlc_data.get("guarded_players", {}):
            guard_player = dlc_data["guarded_players"][target_player]
            guard_role = game_data["players"][guard_player]
            if guard_role.get("original_code") == "guard":
                return False
        
        # 处理魔术师交换
        swapped_players = dlc_data.get("swapped_players")
        if swapped_players:
            target_num = target_role["player_number"]
            if target_num in swapped_players:
                # 找到交换后的目标
                idx = swapped_players.index(target_num)
                other_idx = 1 - idx
                other_num = swapped_players[other_idx]
                other_player = self._get_player_by_number(game_data, other_num)
                if other_player:
                    # 实际效果作用于交换后的玩家
                    target_role = game_data["players"][other_player]
        
        # 检查双面人阵营转换
        if target_role.get("original_code") == "double_face":
            target_role["death_trigger"] = "wolf_kill"
        
        return default_value

    async def modify_guard_protect(self, game_data: Dict, default_value: bool, **kwargs) -> bool:
        """修改守卫守护效果"""
        target_player = kwargs.get('target_player')
        if not target_player:
            return default_value
            
        target_role = game_data["players"][target_player]
        
        # 通灵师无法被守护
        if (target_role.get("original_code") == "spiritualist" and 
            target_role.get("cannot_be_guarded")):
            return False
        
        return default_value

    async def modify_witch_antidote(self, game_data: Dict, default_value: bool, **kwargs) -> bool:
        """修改女巫解药效果"""
        target_player = kwargs.get('target_player')
        if not target_player:
            return default_value
            
        target_role = game_data["players"][target_player]
        
        # 通灵师解药无效
        if (target_role.get("original_code") == "spiritualist" and 
            target_role.get("antidote_ineffective")):
            return False
        
        return default_value

    async def modify_witch_poison(self, game_data: Dict, default_value: bool, **kwargs) -> bool:
        """修改女巫毒药效果"""
        target_player = kwargs.get('target_player')
        if not target_player:
            return default_value
            
        target_role = game_data["players"][target_player]
        
        # 双面人毒药无效
        if (target_role.get("original_code") == "double_face" and 
            target_role.get("immune_to_poison")):
            return False
        
        return default_value

    # === 具体角色行动处理 ===
    
    async def _handle_guard_action(self, user_id: str, game_data: Dict, params: str) -> bool:
        """处理守卫守护"""
        try:
            target_num = int(params.strip())
            target_player = self._get_player_by_number(game_data, target_num)
            if not target_player or target_player not in game_data["alive_players"]:
                await send_api.text_to_user(text="❌ 无效的玩家号码。", user_id=user_id, platform="qq")
                return True
            
            player_role = game_data["players"][user_id]
            
            # 检查是否连续两晚守护同一玩家
            last_guard = player_role.get("last_guard_target")
            if last_guard == target_num:
                await send_api.text_to_user(text="❌ 不能连续两晚守护同一名玩家。", user_id=user_id, platform="qq")
                return True
            
            # 检查守护效果 - 修复参数传递
            can_guard = await self.modify_guard_protect(
                game_data, 
                True,  # default_value
                target_player=target_player
            )
            if not can_guard:
                await send_api.text_to_user(text="❌ 无法守护该玩家。", user_id=user_id, platform="qq")
                return True
            
            # 记录守护行动
            game_data.setdefault("night_actions", {})[user_id] = {
                "type": "guard",
                "target": target_num
            }
            player_role["last_guard_target"] = target_num
            
            # 记录到DLC数据
            dlc_data = game_data["dlc_data"]["chaos_pack"]
            dlc_data.setdefault("guarded_players", {})[target_player] = user_id
            
            await send_api.text_to_user(text=f"✅ 您选择守护玩家 {target_num} 号", user_id=user_id, platform="qq")
            return True
        except ValueError:
            await send_api.text_to_user(text="❌ 守护格式错误。使用: /wwg guard [玩家号码]", user_id=user_id, platform="qq")
            return True

    async def _handle_swap_action(self, user_id: str, game_data: Dict, params: str) -> bool:
        """处理魔术师交换"""
        try:
            params_list = params.split()
            if len(params_list) != 2:
                await send_api.text_to_user(text="❌ 需要两个玩家号码。使用: /wwg swap [号码1] [号码2]", user_id=user_id, platform="qq")
                return True
            
            num1 = int(params_list[0])
            num2 = int(params_list[1])
            player1 = self._get_player_by_number(game_data, num1)
            player2 = self._get_player_by_number(game_data, num2)
            
            if not player1 or not player2 or num1 == num2:
                await send_api.text_to_user(text="❌ 无效的玩家号码。", user_id=user_id, platform="qq")
                return True
            
            # 记录交换行动
            game_data.setdefault("night_actions", {})[user_id] = {
                "type": "swap",
                "targets": [num1, num2]
            }
            
            # 记录到DLC数据
            dlc_data = game_data["dlc_data"]["chaos_pack"]
            dlc_data["swapped_players"] = [num1, num2]
            
            await send_api.text_to_user(text=f"✅ 您交换了玩家 {num1} 号和 {num2} 号的号码牌", user_id=user_id, platform="qq")
            return True
        except ValueError:
            await send_api.text_to_user(text="❌ 交换格式错误。使用: /wwg swap [号码1] [号码2]", user_id=user_id, platform="qq")
            return True

    async def _handle_reveal_action(self, user_id: str, game_data: Dict, params: str) -> bool:
        """处理通灵师查验"""
        try:
            target_num = int(params.strip())
            target_player = self._get_player_by_number(game_data, target_num)
            if not target_player or target_player not in game_data["alive_players"]:
                await send_api.text_to_user(text="❌ 无效的玩家号码。", user_id=user_id, platform="qq")
                return True
            
            target_role = game_data["players"][target_player]
            role_name = target_role["name"]
            
            # 记录查验行动
            game_data.setdefault("night_actions", {})[user_id] = {
                "type": "reveal",
                "target": target_num,
                "result": role_name
            }
            
            await send_api.text_to_user(text=f"🔮 查验结果: 玩家 {target_num} 号是 {role_name}", user_id=user_id, platform="qq")
            return True
        except ValueError:
            await send_api.text_to_user(text="❌ 查验格式错误。使用: /wwg reveal [玩家号码]", user_id=user_id, platform="qq")
            return True

    async def _handle_disguise_action(self, user_id: str, game_data: Dict, params: str) -> bool:
        """处理画皮伪装"""
        try:
            target_num = int(params.strip())
            target_player = self._get_player_by_number(game_data, target_num)
            if not target_player or target_player in game_data["alive_players"]:
                await send_api.text_to_user(text="❌ 只能选择已出局的玩家。", user_id=user_id, platform="qq")
                return True
            
            player_role = game_data["players"][user_id]
            
            if player_role.get("disguise_used", False):
                await send_api.text_to_user(text="❌ 本局游戏已经使用过伪装能力。", user_id=user_id, platform="qq")
                return True
            
            # 检查是否第二夜及以后
            if game_data["day_number"] < 1:  # 第0夜是第一夜
                await send_api.text_to_user(text="❌ 第二夜起才能使用伪装能力。", user_id=user_id, platform="qq")
                return True
            
            target_role = game_data["players"][target_player]
            
            # 记录伪装行动
            game_data.setdefault("night_actions", {})[user_id] = {
                "type": "disguise",
                "target": target_num,
                "disguise_as": target_role["name"]
            }
            
            player_role["disguise_used"] = True
            player_role["disguised_as"] = target_role["name"]
            
            # 记录到DLC数据
            dlc_data = game_data["dlc_data"]["chaos_pack"]
            dlc_data.setdefault("disguised_players", {})[user_id] = target_role["name"]
            
            await send_api.text_to_user(text=f"✅ 您伪装成了 {target_role['name']}", user_id=user_id, platform="qq")
            return True
        except ValueError:
            await send_api.text_to_user(text="❌ 伪装格式错误。使用: /wwg disguise [已出局玩家号码]", user_id=user_id, platform="qq")
            return True

    async def _handle_couple_action(self, user_id: str, game_data: Dict, params: str) -> bool:
        """处理丘比特连接情侣"""
        try:
            params_list = params.split()
            if len(params_list) != 2:
                await send_api.text_to_user(text="❌ 需要两个玩家号码。使用: /wwg couple [号码1] [号码2]", user_id=user_id, platform="qq")
                return True
            
            num1 = int(params_list[0])
            num2 = int(params_list[1])
            player1 = self._get_player_by_number(game_data, num1)
            player2 = self._get_player_by_number(game_data, num2)
            
            if not player1 or not player2 or num1 == num2:
                await send_api.text_to_user(text="❌ 无效的玩家号码。", user_id=user_id, platform="qq")
                return True
            
            # 检查是否第一夜
            if game_data["day_number"] > 0:
                await send_api.text_to_user(text="❌ 只能在第一夜连接情侣。", user_id=user_id, platform="qq")
                return True
            
            # 记录连接行动
            game_data.setdefault("night_actions", {})[user_id] = {
                "type": "couple",
                "targets": [num1, num2]
            }
            
            # 创建情侣关系
            dlc_data = game_data["dlc_data"]["chaos_pack"]
            dlc_data["lovers"] = [player1, player2]
            dlc_data["cupid"] = user_id
            
            # 设置情侣阵营
            game_data["players"][player1]["lover"] = True
            game_data["players"][player2]["lover"] = True
            game_data["players"][user_id]["lover"] = True
            
            await send_api.text_to_user(text=f"✅ 您将玩家 {num1} 号和 {num2} 号结为情侣", user_id=user_id, platform="qq")
            
            # 通知情侣
            try:
                await send_api.text_to_user(
                    text=f"💕 你被丘比特选中成为情侣！你的情侣是玩家 {num2 if num1 == game_data['players'][player1]['player_number'] else num1} 号",
                    user_id=player1,
                    platform="qq"
                )
                await send_api.text_to_user(
                    text=f"💕 你被丘比特选中成为情侣！你的情侣是玩家 {num1 if num2 == game_data['players'][player2]['player_number'] else num2} 号",
                    user_id=player2,
                    platform="qq"
                )
            except:
                pass
            
            return True
        except ValueError:
            await send_api.text_to_user(text="❌ 连接格式错误。使用: /wwg couple [号码1] [号码2]", user_id=user_id, platform="qq")
            return True

    # === 辅助方法 ===
    
    def _get_player_by_number(self, game_data: Dict, player_num: int) -> Optional[str]:
        """通过玩家号码获取玩家ID"""
        for player_id, role_info in game_data["players"].items():
            if role_info["player_number"] == player_num:
                return player_id
        return None

    async def _check_hidden_wolf_transform(self, game_data: Dict):
        """检查隐狼变身"""
        for player_id, role_info in game_data["players"].items():
            if (role_info.get("original_code") == "hidden_wolf" and 
                role_info.get("alive") and 
                not role_info.get("can_kill")):
                
                # 检查是否还有其他狼人存活
                other_wolves = [pid for pid in game_data["alive_players"] 
                              if pid != player_id and 
                              game_data["players"][pid].get("team") == "werewolf" and
                              game_data["players"][pid].get("original_code") != "hidden_wolf"]
                
                if not other_wolves:
                    role_info["can_kill"] = True
                    role_info["night_action"] = True
                    role_info["action_command"] = "kill"
                    try:
                        await send_api.text_to_user(
                            text="🐺 你的狼队友全部出局，你获得了刀人能力！现在可以使用 /wwg kill 命令",
                            user_id=player_id,
                            platform="qq"
                        )
                    except:
                        pass

    async def _check_successor_inheritance(self, game_data: Dict):
        """检查继承者技能继承"""
        for player_id, role_info in game_data["players"].items():
            if (role_info.get("original_code") == "successor" and 
                role_info.get("alive") and 
                not role_info.get("inherited_skill")):
                
                player_num = role_info["player_number"]
                total_players = len(game_data["players"])
                
                # 检查相邻玩家
                adjacent_players = []
                if player_num > 1:
                    left_player = self._get_player_by_number(game_data, player_num - 1)
                    if left_player:
                        adjacent_players.append(left_player)
                if player_num < total_players:
                    right_player = self._get_player_by_number(game_data, player_num + 1)
                    if right_player:
                        adjacent_players.append(right_player)
                
                # 检查相邻神民是否出局
                for adj_player in adjacent_players:
                    adj_role = game_data["players"][adj_player]
                    if (not adj_role.get("alive") and 
                        adj_role.get("team") == "village" and 
                        adj_role.get("sub_role")):
                        
                        # 继承技能
                        inherited_code = adj_role.get("original_code")
                        role_info["inherited_skill"] = inherited_code
                        role_info["sub_role"] = True
                        role_info["night_action"] = adj_role.get("night_action")
                        role_info["action_command"] = adj_role.get("action_command")
                        role_info["name"] = f"继承者({adj_role['name']})"
                        
                        # 记录到DLC数据
                        dlc_data = game_data["dlc_data"]["chaos_pack"]
                        dlc_data["inherited_skills"][player_id] = inherited_code
                        
                        try:
                            await send_api.text_to_user(
                                text=f"🎯 你继承了 {adj_role['name']} 的能力！现在可以使用 /wwg {adj_role.get('action_command', '')} 命令",
                                user_id=player_id,
                                platform="qq"
                            )
                        except:
                            pass
                        break

    async def _handle_lover_suicide(self, game_data: Dict, dead_player: str, reason: str):
        """处理情侣殉情"""
        dlc_data = game_data["dlc_data"]["chaos_pack"]
        lovers = dlc_data.get("lovers", [])
        
        if dead_player in lovers:
            # 找到另一个情侣
            other_lover = next((lid for lid in lovers if lid != dead_player), None)
            if other_lover and game_data["players"][other_lover].get("alive"):
                # 殉情
                other_num = game_data["players"][other_lover]["player_number"]
                group_id = game_data.get("group_id")
                if group_id and group_id != "private":
                    try:
                        await send_api.text_to_group(
                            text=f"💔 玩家 {other_num} 号因情侣死亡而殉情",
                            group_id=group_id,
                            platform="qq"
                        )
                    except:
                        pass
                
                # 标记死亡但不立即移除，让主插件处理
                game_data["players"][other_lover]["death_trigger"] = "suicide"

    async def _handle_double_face_conversion(self, game_data: Dict, dead_player: str, reason: str):
        """处理双面人阵营转换"""
        dead_role = game_data["players"][dead_player]
        
        if (dead_role.get("original_code") == "double_face" and 
            dead_role.get("alive") and
            dead_role.get("can_change_team")):
            
            # 只在真正死亡前转换阵营（alive=True时）
            if reason == "wolf_kill":
                dead_role["team"] = "werewolf"
                dead_role["death_trigger"] = "converted"
                try:
                    await send_api.text_to_user(
                        text="🐺 你被狼人袭击，现在加入了狼人阵营！",
                        user_id=dead_player,
                        platform="qq"
                    )
                except:
                    pass
            elif reason == "vote":
                dead_role["team"] = "village"
                dead_role["death_trigger"] = "converted"
                try:
                    await send_api.text_to_user(
                        text="👨‍🌾 你被投票放逐，现在加入了村庄阵营！",
                        user_id=dead_player,
                        platform="qq"
                    )
                except:
                    pass
            
            # 记录转换
            dlc_data = game_data["dlc_data"]["chaos_pack"]
            dlc_data["double_face_conversions"][dead_player] = dead_role["team"]

    async def _handle_successor_adjacent_death(self, game_data: Dict, dead_player: str):
        """处理继承者相邻神民死亡"""
        # 触发继承检查（在夜晚开始时处理）
        pass

    async def _apply_swapped_effects(self, game_data: Dict, action_type: str, target_num: int) -> int:
        """应用魔术师交换效果"""
        dlc_data = game_data["dlc_data"]["chaos_pack"]
        swapped_players = dlc_data.get("swapped_players")
        
        if swapped_players and target_num in swapped_players:
            idx = swapped_players.index(target_num)
            other_idx = 1 - idx
            return swapped_players[other_idx]
        
        return target_num

# 导出扩展包实例
chaos_pack = ChaosPackDLC()