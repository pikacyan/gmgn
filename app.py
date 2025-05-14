from telethon import TelegramClient, events, errors
import aiohttp
import asyncio
import time
import logging
import json
import os
import yaml
import re
from urllib3.util.retry import Retry

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("gmgn_bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("GMGN_Bot")


class ConfigManager:
    """配置管理类"""

    @staticmethod
    def load_config():
        """从配置文件加载配置"""
        try:
            if os.path.exists("config.yaml"):
                with open("config.yaml", "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)
                logger.info("已从config.yaml加载配置")

                # 确保必要的配置项存在
                if "wallet_address" not in config:
                    logger.warning("配置中缺少wallet_address参数，将无法验证代币余额")
                    config["wallet_address"] = ""

                # 确保交易重试配置项存在
                if "max_transaction_retries" not in config:
                    config["max_transaction_retries"] = 3  # 默认最多重试3次
                if "retry_delay" not in config:
                    config["retry_delay"] = 5  # 默认重试间隔5秒

                # 确保交易检查配置项存在
                if "check_balance_only_after_transaction" not in config:
                    config["check_balance_only_after_transaction"] = True

                # 确保价格检查间隔存在
                if "price_check_interval" not in config:
                    config["price_check_interval"] = 30  # 默认30秒检查一次

                # 确保买入确认延迟存在
                if "buy_confirmation_delay" not in config:
                    config["buy_confirmation_delay"] = 5  # 默认5秒

                return config
            else:
                logger.error("配置文件不存在，请创建config.yaml文件")
                raise FileNotFoundError("配置文件不存在")
        except Exception as e:
            logger.error(f"配置加载失败: {e}")
            raise


class ContractValidator:
    """合约验证类"""

    def __init__(self, config):
        self.config = config

    async def verify_contract(self, ca):
        """异步验证合约地址是否存在"""
        try:
            # 首先尝试使用BSCScan API直接验证合约是否存在
            if (
                "bscscan_api_key" in self.config
                and self.config["bscscan_api_key"]
                and self.config["bscscan_api_key"] != "YOUR_BSCSCAN_API_KEY"
            ):
                bsc_url = f"https://api.bscscan.com/api?module=contract&action=getabi&address={ca}&apikey={self.config['bscscan_api_key']}"

                async with aiohttp.ClientSession() as session:
                    async with session.get(bsc_url, timeout=10) as response:
                        bsc_data = await response.json()

                        # 检查合约是否存在
                        if (
                            bsc_data["status"] == "1"
                            or bsc_data["result"] == "Contract source code not verified"
                        ):
                            logger.info(f"BSCScan API 验证合约 {ca} 存在")
                            return True, "合约地址有效"

            # 方法2: 使用DexScreener API验证是否有交易对
            url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    data = await response.json()
                    if "pairs" in data and data["pairs"] and len(data["pairs"]) > 0:
                        return True, "合约地址有效"

            # 如果BSCScan API未配置或验证失败，且DexScreener也没有数据，再尝试BSCScan合约代码检查
            if (
                "bscscan_api_key" not in self.config
                or self.config["bscscan_api_key"] == "YOUR_BSCSCAN_API_KEY"
                or not self.config["bscscan_api_key"]
            ):
                # 使用BSCScan API检查合约代码
                logger.warning(f"BSCScan API密钥未配置或无效，无法完全验证合约 {ca}")
                return (
                    False,
                    "BSCScan API密钥未配置，无法完全验证合约，且找不到该合约地址的交易对",
                )

            # 如果到这里，说明合约可能存在但没有交易对
            return False, "找不到该合约地址的交易对，可能是新合约或未上线"
        except Exception as e:
            logger.error(f"验证合约地址时出错: {e}")
            return False, f"验证合约地址时出错: {e}"


class PriceMonitor:
    """价格监控类"""

    @staticmethod
    async def get_price_dexscreener(ca):
        """从DexScreener获取当前价格"""
        url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    data = await response.json()
                    if "pairs" in data and data["pairs"] and len(data["pairs"]) > 0:
                        return float(data["pairs"][0]["priceUsd"])
            logger.warning(f"获取价格数据格式不正确: {data}")
            return None
        except Exception as e:
            logger.error(f"DexScreener获取价格失败: {e}")
            return None


class BlockchainInteraction:
    """区块链交互类"""

    def __init__(self, config):
        self.config = config

    async def get_transaction_by_hash(self, tx_hash):
        """异步通过交易哈希获取交易详情"""
        try:
            # 确保有BSCScan API密钥
            if (
                "bscscan_api_key" not in self.config
                or not self.config["bscscan_api_key"]
                or self.config["bscscan_api_key"] == "YOUR_BSCSCAN_API_KEY"
            ):
                return False, "BSCScan API密钥未配置，无法查询交易详情"

            # 使用BSCScan API查询交易详情
            api_url = f"https://api.bscscan.com/api?module=proxy&action=eth_getTransactionByHash&txhash={tx_hash}&apikey={self.config['bscscan_api_key']}"

            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, timeout=10) as response:
                    data = await response.json()

                    if "result" in data and data["result"]:
                        return True, data["result"]
                    else:
                        return False, f"查询失败: {data.get('message', '未知错误')}"
        except Exception as e:
            logger.error(f"查询交易详情时出错: {e}")
            return False, f"查询出错: {e}"

    async def get_contract_address_from_transaction(self, tx_hash):
        """通过交易哈希获取相关的合约地址"""
        success, tx_data = await self.get_transaction_by_hash(tx_hash)
        if not success:
            logger.warning(f"无法获取交易 {tx_hash} 的详情: {tx_data}")
            return None

        # 检查交易是否是与合约的交互
        if "to" in tx_data and tx_data["to"]:
            # 这可能是一个代币合约地址
            potential_contract = tx_data["to"]

            # 验证这是否是一个有效的合约地址
            validator = ContractValidator(self.config)
            is_valid, _ = await validator.verify_contract(potential_contract)
            if is_valid:
                return potential_contract

        # 如果直接方法失败，尝试获取内部交易
        try:
            api_url = f"https://api.bscscan.com/api?module=account&action=txlistinternal&txhash={tx_hash}&apikey={self.config['bscscan_api_key']}"

            async with aiohttp.ClientSession() as session:
                async with session.get(api_url) as response:
                    data = await response.json()

                    if (
                        "result" in data
                        and isinstance(data["result"], list)
                        and len(data["result"]) > 0
                    ):
                        for tx in data["result"]:
                            if "contractAddress" in tx and tx["contractAddress"]:
                                # 验证这是否是一个有效的合约地址
                                validator = ContractValidator(self.config)
                                is_valid, _ = await validator.verify_contract(
                                    tx["contractAddress"]
                                )
                                if is_valid:
                                    return tx["contractAddress"]
        except Exception as e:
            logger.error(f"获取内部交易时出错: {e}")

        # 如果上述方法都失败，尝试获取代币转账事件
        try:
            api_url = f"https://api.bscscan.com/api?module=account&action=tokentx&txhash={tx_hash}&apikey={self.config['bscscan_api_key']}"

            async with aiohttp.ClientSession() as session:
                async with session.get(api_url) as response:
                    data = await response.json()

                    if (
                        "result" in data
                        and isinstance(data["result"], list)
                        and len(data["result"]) > 0
                    ):
                        # 返回第一个代币合约地址
                        return data["result"][0]["contractAddress"]
        except Exception as e:
            logger.error(f"获取代币转账事件时出错: {e}")

        return None

    async def check_token_balance(self, wallet_address, token_address):
        """异步检查指定钱包地址中某代币的余额"""
        try:
            if not wallet_address or not token_address:
                return False, "钱包地址或代币地址为空"

            # 确保有BSCScan API密钥
            if (
                "bscscan_api_key" not in self.config
                or not self.config["bscscan_api_key"]
                or self.config["bscscan_api_key"] == "YOUR_BSCSCAN_API_KEY"
            ):
                return False, "BSCScan API密钥未配置，无法查询链上余额"

            # 使用BSCScan API查询代币余额
            api_url = f"https://api.bscscan.com/api?module=account&action=tokenbalance&contractaddress={token_address}&address={wallet_address}&tag=latest&apikey={self.config['bscscan_api_key']}"

            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, timeout=10) as response:
                    data = await response.json()

                    if data["status"] == "1":
                        balance = int(data["result"])
                        if balance > 0:
                            return True, f"余额: {balance}"
                        else:
                            return False, "余额为零"
                    else:
                        return False, f"查询失败: {data['message']}"
        except Exception as e:
            logger.error(f"查询代币余额时出错: {e}")
            return False, f"查询出错: {e}"


class TransactionManager:
    """交易管理类"""

    @staticmethod
    def extract_transaction_hash(event_message):
        """从消息中提取交易哈希，支持HTML格式"""
        # 如果传入的是字符串，使用正则表达式提取
        if isinstance(event_message, str):
            text = event_message

            # 尝试匹配 bscscan (https://bscscan.com/tx/0x...) 格式
            tx_hash_match = re.search(
                r"bscscan(?:\s*\(?https?://(?:www\.)?bscscan\.com/tx/([a-fA-F0-9]{64})\)?)?",
                text,
            )
            if tx_hash_match and tx_hash_match.group(1):
                return tx_hash_match.group(1)

            # 尝试匹配 bscscan 后面跟着的交易哈希
            tx_hash_match = re.search(r"bscscan.*?(0x[a-fA-F0-9]{64})", text)
            if tx_hash_match:
                return tx_hash_match.group(1)

            # 尝试匹配直接的交易哈希格式
            tx_hash_match = re.search(r"0x[a-fA-F0-9]{64}", text)
            if tx_hash_match:
                return tx_hash_match.group(0)

            return None

        # 如果传入的是消息对象，检查实体
        try:
            # 检查消息中的URL实体
            for entity in event_message.entities or []:
                if hasattr(entity, "url") and entity.url:
                    # 从URL中提取交易哈希
                    url = entity.url
                    tx_hash_match = re.search(
                        r"bscscan\.com/tx/(0x[a-fA-F0-9]{64})", url
                    )
                    if tx_hash_match:
                        return tx_hash_match.group(1)

            # 如果没有找到URL实体，尝试从文本中提取
            return TransactionManager.extract_transaction_hash(event_message.message)
        except Exception as e:
            logger.error(f"从消息中提取交易哈希时出错: {e}")
            return None

    @staticmethod
    def save_transaction(ca, action, price, amount=None, user_id=None):
        """保存交易记录到文件"""
        try:
            transaction = {
                "timestamp": time.time(),
                "contract": ca,
                "action": action,
                "price": price,
                "amount": amount,
                "user_id": user_id,
            }
            with open("transactions.json", "a", encoding="utf-8") as f:
                f.write(json.dumps(transaction) + "\n")
        except Exception as e:
            logger.error(f"保存交易记录失败: {e}")


class BSCBot:
    """BSC交易机器人主类"""

    def __init__(self):
        self.config = ConfigManager.load_config()
        self.price_map = {}
        self.pending_transactions = {}
        self.client = None
        self.blockchain = BlockchainInteraction(self.config)
        self.validator = ContractValidator(self.config)

    def is_authorized(self, user_id):
        """检查用户是否授权"""
        if "authorized_users" in self.config and isinstance(
            self.config["authorized_users"], list
        ):
            return user_id in self.config["authorized_users"]
        return False

    def cleanup_pending_transactions(self):
        """清理超过5分钟的待处理交易"""
        current_time = time.time()
        expired_threshold = 300  # 5分钟

        for tx_id in list(self.pending_transactions.keys()):
            tx_data = self.pending_transactions[tx_id]
            if current_time - tx_data["timestamp"] > expired_threshold:
                logger.warning(f"交易 {tx_id} 已超过5分钟未确认，从待处理列表中移除")
                del self.pending_transactions[tx_id]

    async def connect_client(self):
        """连接到Telegram客户端，包含重连逻辑"""
        # 使用用户账号登录
        client = TelegramClient("bsc", self.config["api_id"], self.config["api_hash"])

        try:
            # 如果配置了电话号码，则使用电话号码登录
            if "phone" in self.config and self.config["phone"]:
                await client.start(phone=self.config["phone"])
            else:
                # 否则使用交互式登录
                await client.start()

            logger.info("成功以用户身份登录Telegram")
            return client
        except Exception as e:
            logger.error(f"连接Telegram失败: {e}")
            raise

    async def setup_message_handler(self):
        """设置消息处理器"""

        @self.client.on(events.NewMessage)
        async def handler(event):
            try:
                user_id = event.sender_id
                text = event.message.message.strip()

                # 处理命令 (忽略所有命令)
                if text.startswith("/"):
                    return

                # 处理合约地址，只接受授权用户的消息
                if text.startswith("0x") and len(text) == 42:
                    # 检查用户是否授权
                    if not self.is_authorized(user_id):
                        logger.warning(f"未授权用户 {user_id} 尝试发送合约地址: {text}")
                        await self.client.send_message(user_id, "您没有权限使用此功能")
                        return

                    ca = text
                    logger.info(f"收到授权用户 {user_id} 的合约地址: {ca}")

                    # 验证合约地址是否存在
                    is_valid, message = await self.validator.verify_contract(ca)
                    if not is_valid:
                        logger.warning(f"无效的合约地址: {ca}, 原因: {message}")
                        await self.client.send_message(
                            user_id, f"无效的合约地址: {message}"
                        )
                        return

                    logger.info(f"合约地址验证通过: {ca}")
                    await self.client.send_message(
                        user_id, f"合约地址验证通过，准备买入..."
                    )

                    # 发送 /buy 指令到交易机器人
                    buy_cmd = f"/buy {ca} {self.config['buy_amount']}"
                    target = (
                        self.config.get("bot_chat_id", "")
                        or self.config["bot_username"]
                    )

                    # 记录待处理的买入交易，添加重试计数
                    tx_id = f"buy_{ca}_{int(time.time())}"
                    self.pending_transactions[tx_id] = {
                        "ca": ca,
                        "type": "buy",
                        "user_id": user_id,
                        "timestamp": time.time(),
                        "retry_count": 0,  # 初始化重试计数
                        "max_retries": self.config["max_transaction_retries"],
                    }

                    await self.client.send_message(target, buy_cmd)
                    logger.info(f"已发送买入指令: {buy_cmd}")

                    # 等待几秒确认交易完成
                    await asyncio.sleep(self.config["buy_confirmation_delay"])

                    # 重试获取价格，最多3次
                    price = None
                    for attempt in range(3):
                        price = await PriceMonitor.get_price_dexscreener(ca)
                        if price:
                            break
                        logger.warning(f"获取价格尝试 {attempt+1}/3 失败，重试中...")
                        await asyncio.sleep(2)

                    if price:
                        self.price_map[ca] = {
                            "buy_price": price,
                            "buy_time": time.time(),
                            "take_profit": self.config["target_gain_percent"],
                            "stop_loss": self.config["stop_loss_percent"],
                            "user_id": user_id,  # 记录下单用户ID
                        }
                        logger.info(f"用户 {user_id} 买入 {ca} 价格: {price} USD")
                        TransactionManager.save_transaction(
                            ca, "buy", price, self.config["buy_amount"], user_id
                        )

                        await self.client.send_message(
                            user_id,
                            f"""已买入 {ca}
买入价格: ${price:.8f}
止盈设置: {self.config["target_gain_percent"]}%
止损设置: {self.config["stop_loss_percent"]}%
开始监控价格变化...""",
                        )
                    else:
                        logger.error(f"无法获取价格，已放弃监控该合约: {ca}")
                        await self.client.send_message(
                            user_id, "无法获取价格，交易可能已完成但无法监控价格变化"
                        )

            except Exception as e:
                logger.error(f"处理消息时出错: {e}")

        # 监听交易机器人的回复
        @self.client.on(events.NewMessage(from_users=self.config["bot_username"]))
        async def bot_response_handler(event):
            try:
                text = event.message.message.strip()
                logger.info(f"收到交易机器人消息: {text}")

                # 检测买入成功的消息
                if (
                    "已成功买入" in text
                    or "successfully bought" in text.lower()
                    or ("交易成功" in text and "买入" in text)
                ):
                    # 先尝试从消息中提取合约地址
                    contract_match = re.search(r"0x[a-fA-F0-9]{40}", text)
                    ca = None

                    if contract_match:
                        ca = contract_match.group(0)
                    else:
                        # 如果没有直接找到合约地址，尝试从交易哈希获取
                        tx_hash = TransactionManager.extract_transaction_hash(
                            event.message
                        )
                        if tx_hash:
                            logger.info(f"从消息中提取到交易哈希: {tx_hash}")
                            ca = await self.blockchain.get_contract_address_from_transaction(
                                tx_hash
                            )
                            if ca:
                                logger.info(f"从交易 {tx_hash} 中获取到合约地址: {ca}")

                    if ca:
                        # 清理相关的待处理交易
                        for tx_id in list(self.pending_transactions.keys()):
                            if (
                                self.pending_transactions[tx_id]["ca"] == ca
                                and self.pending_transactions[tx_id]["type"] == "buy"
                            ):
                                logger.info(
                                    f"买入交易 {tx_id} 已成功，从待处理列表中移除"
                                )
                                del self.pending_transactions[tx_id]

                        # 买入成功后立即检查余额
                        if self.config["wallet_address"] and ca in self.price_map:
                            logger.info(f"买入成功后检查合约 {ca} 的余额")
                            has_balance = False
                            max_retries = 3

                            for retry in range(max_retries):
                                has_balance, message = (
                                    await self.blockchain.check_token_balance(
                                        self.config["wallet_address"], ca
                                    )
                                )

                                if has_balance:
                                    logger.info(
                                        f"链上确认持有代币 (尝试 {retry+1}/{max_retries}): {message}"
                                    )
                                    # 标记该合约已经确认持有代币
                                    self.price_map[ca]["balance_confirmed"] = True
                                    break
                                else:
                                    logger.warning(
                                        f"链上未检测到代币 (尝试 {retry+1}/{max_retries}): {message}"
                                    )
                                    if (
                                        retry < max_retries - 1
                                    ):  # 如果不是最后一次尝试，则等待
                                        await asyncio.sleep(5)  # 等待5秒再次检查

                            if not has_balance:
                                logger.warning(
                                    f"买入后多次检查仍未在链上检测到代币 {ca}"
                                )
                                # 通知用户但继续监控
                                user_id = self.price_map[ca].get("user_id")
                                if user_id:
                                    try:
                                        await self.client.send_message(
                                            user_id,
                                            f"警告: 交易机器人报告买入成功，但链上未检测到代币 {ca}，将继续监控价格变化",
                                        )
                                    except Exception as e:
                                        logger.error(f"通知用户 {user_id} 失败: {e}")
                        else:
                            logger.warning("检测到买入成功消息，但无法提取合约地址")

                # 检测交易失败的消息
                elif "链上交易失败" in text or "滑点不够" in text:
                    logger.warning(f"检测到交易失败消息: {text}")

                    # 查找最近的待处理交易
                    if self.pending_transactions:
                        # 按时间戳排序，获取最近的交易
                        sorted_transactions = sorted(
                            self.pending_transactions.items(),
                            key=lambda x: x[1]["timestamp"],
                            reverse=True,
                        )

                        if sorted_transactions:
                            tx_id, tx_data = sorted_transactions[0]
                            ca = tx_data["ca"]
                            tx_type = tx_data["type"]
                            user_id = tx_data["user_id"]

                            # 检查是否需要重试
                            retry_count = tx_data.get("retry_count", 0)
                            max_retries = tx_data.get(
                                "max_retries", self.config["max_transaction_retries"]
                            )

                            if retry_count < max_retries - 1:  # 还可以重试
                                # 增加重试计数
                                retry_count += 1
                                logger.info(
                                    f"{tx_type.capitalize()}交易失败，准备第 {retry_count+1}/{max_retries} 次重试: {ca}"
                                )

                                # 更新交易记录
                                new_tx_id = f"{tx_type}_{ca}_{int(time.time())}"
                                self.pending_transactions[new_tx_id] = {
                                    "ca": ca,
                                    "type": tx_type,
                                    "user_id": user_id,
                                    "timestamp": time.time(),
                                    "retry_count": retry_count,
                                    "max_retries": max_retries,
                                }

                                # 从旧的待处理交易中移除
                                del self.pending_transactions[tx_id]

                                # 等待一段时间后重试
                                await asyncio.sleep(self.config["retry_delay"])

                                # 重新发送交易指令
                                target = (
                                    self.config.get("bot_chat_id", "")
                                    or self.config["bot_username"]
                                )
                                if tx_type == "buy":
                                    cmd = f"/buy {ca} {self.config['buy_amount']}"
                                else:  # sell
                                    cmd = f"/sell {ca} 100"

                                await self.client.send_message(target, cmd)
                                logger.info(f"已重新发送{tx_type}指令: {cmd}")

                                # 通知用户正在重试
                                if user_id:
                                    try:
                                        await self.client.send_message(
                                            user_id,
                                            f"{tx_type.capitalize()}交易失败，正在进行第 {retry_count+1}/{max_retries} 次重试...",
                                        )
                                    except Exception as e:
                                        logger.error(f"通知用户 {user_id} 失败: {e}")
                            else:
                                # 达到最大重试次数，放弃交易
                                logger.warning(
                                    f"{tx_type.capitalize()}交易在 {max_retries} 次尝试后仍然失败: {ca}"
                                )

                                # 从待处理交易中移除
                                del self.pending_transactions[tx_id]

                                # 如果是买入交易失败，检查是否已经添加到price_map中，如果是则移除
                                if tx_type == "buy" and ca in self.price_map:
                                    del self.price_map[ca]
                                    logger.info(
                                        f"由于买入多次失败，已停止监控合约 {ca}"
                                    )

                            if user_id:
                                try:
                                    # 通知用户交易失败
                                    failure_message = f"警告: {tx_type}合约 {ca} 的交易失败，原因: {text}\n"
                                    if tx_type == "buy":
                                        failure_message += "请检查滑点设置或稍后重试。"
                                    else:  # sell
                                        failure_message += "卖出失败，将继续监控价格变化。请手动检查或稍后重试卖出。"

                                    await self.client.send_message(
                                        user_id, failure_message
                                    )
                                    logger.info(f"已通知用户 {user_id} 交易失败")
                                except Exception as e:
                                    logger.error(f"通知用户 {user_id} 失败: {e}")
                        else:
                            logger.warning(
                                "检测到交易失败消息，但没有找到最近的待处理交易"
                            )
                    else:
                        # 备用方案：尝试从最近的监控列表中找
                        recent_contracts = list(self.price_map.keys())
                        if recent_contracts:
                            # 获取最近添加的合约（假设是当前操作的合约）
                            latest_contract = recent_contracts[-1]
                            user_id = self.price_map[latest_contract].get("user_id")

                            if user_id:
                                try:
                                    # 通知用户交易失败
                                    await self.client.send_message(
                                        user_id,
                                        f"警告: 合约 {latest_contract} 的交易失败，原因: {text}\n请手动检查交易状态或重试。",
                                    )
                                    logger.info(f"已通知用户 {user_id} 交易失败")
                                except Exception as e:
                                    logger.error(f"通知用户 {user_id} 失败: {e}")
                        else:
                            logger.warning("检测到交易失败消息，但无法确定相关合约地址")

                # 检测卖出成功的消息
                elif (
                    "已成功卖出" in text
                    or "successfully sold" in text.lower()
                    or ("交易成功" in text and "卖出" in text)
                ):
                    # 先尝试从消息中提取合约地址
                    contract_match = re.search(r"0x[a-fA-F0-9]{40}", text)
                    ca = None

                    if contract_match:
                        ca = contract_match.group(0)
                    else:
                        # 如果没有直接找到合约地址，尝试从交易哈希获取
                        tx_hash = TransactionManager.extract_transaction_hash(
                            event.message
                        )
                        if tx_hash:
                            logger.info(f"从消息中提取到交易哈希: {tx_hash}")
                            ca = await self.blockchain.get_contract_address_from_transaction(
                                tx_hash
                            )
                            if ca:
                                logger.info(f"从交易 {tx_hash} 中获取到合约地址: {ca}")

                    if ca:
                        # 清理相关的待处理交易
                        for tx_id in list(self.pending_transactions.keys()):
                            if (
                                self.pending_transactions[tx_id]["ca"] == ca
                                and self.pending_transactions[tx_id]["type"] == "sell"
                            ):
                                logger.info(
                                    f"卖出交易 {tx_id} 已成功，从待处理列表中移除"
                                )
                                del self.pending_transactions[tx_id]

                        if ca in self.price_map:
                            logger.info(f"检测到合约 {ca} 已成功卖出，准备检查链上余额")

                            # 如果配置了钱包地址，验证链上余额
                            if self.config["wallet_address"]:
                                # 添加重试逻辑，最多重试3次
                                has_balance = False
                                max_retries = 3

                                for retry in range(max_retries):
                                    has_balance, message = (
                                        await self.blockchain.check_token_balance(
                                            self.config["wallet_address"], ca
                                        )
                                    )

                                    if not has_balance:
                                        # 如果没有余额，表示已经成功卖出
                                        logger.info(
                                            f"链上检测合约 {ca} 余额为零 (尝试 {retry+1}/{max_retries}): {message}"
                                        )
                                        break
                                    else:
                                        # 如果有余额，可能交易尚未确认，等待
                                        logger.warning(
                                            f"链上检测到仍持有代币 (尝试 {retry+1}/{max_retries}): {message}"
                                        )
                                        if (
                                            retry < max_retries - 1
                                        ):  # 如果不是最后一次尝试，则等待
                                            await asyncio.sleep(5)  # 等待5秒再次检查

                                # 如果经过多次检查后仍然持有代币
                                if has_balance:
                                    logger.warning(
                                        f"链上多次检测到仍持有代币: {message}，继续监控"
                                    )
                                    # 通知用户但继续监控
                                    user_id = self.price_map[ca].get("user_id")
                                    if user_id:
                                        try:
                                            await self.client.send_message(
                                                user_id,
                                                f"警告: 交易机器人报告卖出成功，但链上多次检测到仍持有代币 {ca}，继续监控价格变化",
                                            )
                                        except Exception as e:
                                            logger.error(
                                                f"通知用户 {user_id} 失败: {e}"
                                            )
                                else:
                                    # 如果没有余额，表示已经成功卖出
                                    logger.info(
                                        f"链上确认合约 {ca} 已成功卖出，停止监控"
                                    )

                                    # 如果有用户ID，通知用户
                                    user_id = self.price_map[ca].get("user_id")
                                    if user_id:
                                        try:
                                            await self.client.send_message(
                                                user_id,
                                                f"链上确认合约 {ca} 已成功卖出，停止监控价格变化",
                                            )
                                        except Exception as e:
                                            logger.error(
                                                f"通知用户 {user_id} 失败: {e}"
                                            )

                                    # 从监控列表中移除
                                    del self.price_map[ca]
                            else:
                                # 如果没有配置钱包地址，直接停止监控
                                # 如果有用户ID，通知用户
                                user_id = self.price_map[ca].get("user_id")
                                if user_id:
                                    try:
                                        await self.client.send_message(
                                            user_id,
                                            f"检测到合约 {ca} 已成功卖出，停止监控价格变化",
                                        )
                                    except Exception as e:
                                        logger.error(f"通知用户 {user_id} 失败: {e}")

                                # 从监控列表中移除
                                del self.price_map[ca]
                        else:
                            logger.warning(
                                f"检测到合约 {ca} 卖出成功，但不在监控列表中"
                            )
                    else:
                        logger.warning("检测到卖出成功消息，但无法提取合约地址")

            except Exception as e:
                logger.error(f"处理交易机器人消息时出错: {e}")

    async def monitor_price(self):
        """定时检查价格是否达到目标涨幅或止损点"""
        while True:
            try:
                # 清理过期的待处理交易
                self.cleanup_pending_transactions()

                for ca, data in list(self.price_map.items()):
                    buy_price = data["buy_price"]
                    take_profit = data["take_profit"]
                    stop_loss = data["stop_loss"]
                    user_id = data.get("user_id")  # 获取用户ID

                    # 如果配置了钱包地址，并且需要检查余额（交易后或首次检查）
                    if self.config["wallet_address"] and (
                        data.get("needs_balance_check", False)
                        or not self.config.get(
                            "check_balance_only_after_transaction", True
                        )
                    ):
                        # 添加重试逻辑，最多重试3次
                        has_balance = False
                        max_retries = 3

                        for retry in range(max_retries):
                            has_balance, message = (
                                await self.blockchain.check_token_balance(
                                    self.config["wallet_address"], ca
                                )
                            )

                            if not has_balance:
                                # 如果没有余额，表示已经成功卖出
                                logger.info(
                                    f"链上检测合约 {ca} 余额为零 (尝试 {retry+1}/{max_retries}): {message}"
                                )

                                # 如果确认没有余额，从监控列表中移除
                                user_id = self.price_map[ca].get("user_id")
                                if user_id:
                                    try:
                                        await self.client.send_message(
                                            user_id,
                                            f"链上检测到合约 {ca} 已卖出，停止监控价格变化",
                                        )
                                    except Exception as e:
                                        logger.error(f"通知用户 {user_id} 失败: {e}")

                                # 从监控列表中移除
                                del self.price_map[ca]
                                break
                            else:
                                # 如果有余额，可能交易尚未确认，等待
                                logger.warning(
                                    f"链上检测到仍持有代币 (尝试 {retry+1}/{max_retries}): {message}"
                                )
                                if (
                                    retry < max_retries - 1
                                ):  # 如果不是最后一次尝试，则等待
                                    await asyncio.sleep(5)  # 等待5秒再次检查

                        # 如果经过多次检查后仍然持有代币
                        if has_balance:
                            logger.warning(
                                f"链上多次检测到仍持有代币: {message}，继续监控"
                            )
                            # 重置检查标志，避免每次都检查
                            self.price_map[ca]["needs_balance_check"] = False

                            # 只在首次检测到时通知用户
                            if not data.get("balance_notified", False):
                                user_id = self.price_map[ca].get("user_id")
                                if user_id:
                                    try:
                                        await self.client.send_message(
                                            user_id,
                                            f"链上检测到仍持有代币 {ca}，将继续监控价格变化",
                                        )
                                        # 标记已通知，避免重复通知
                                        self.price_map[ca]["balance_notified"] = True
                                    except Exception as e:
                                        logger.error(f"通知用户 {user_id} 失败: {e}")

                    current_price = await PriceMonitor.get_price_dexscreener(ca)

                    if current_price:
                        gain = ((current_price - buy_price) / buy_price) * 100
                        logger.info(f"合约 {ca} 当前涨幅: {gain:.2f}%")

                        # 止盈
                        if gain >= take_profit:
                            try:
                                # 确定发送目标
                                target = (
                                    self.config.get("bot_chat_id", "")
                                    or self.config["bot_username"]
                                )

                                sell_cmd = f"/sell {ca} 100"  # 卖出全部

                                # 记录待处理的卖出交易
                                tx_id = f"sell_{ca}_{int(time.time())}"
                                self.pending_transactions[tx_id] = {
                                    "ca": ca,
                                    "type": "sell",
                                    "user_id": user_id,
                                    "timestamp": time.time(),
                                    "reason": "take_profit",
                                    "retry_count": 0,  # 初始化重试计数
                                    "max_retries": self.config[
                                        "max_transaction_retries"
                                    ],
                                }

                                await self.client.send_message(target, sell_cmd)
                                logger.info(f"已发送卖出指令(止盈): {sell_cmd}")

                                TransactionManager.save_transaction(
                                    ca, "sell", current_price, "100%", user_id
                                )

                                # 如果有用户ID，通知用户
                                if user_id:
                                    try:
                                        await self.client.send_message(
                                            user_id,
                                            f"""止盈触发! 已卖出 {ca}
买入价格: ${buy_price:.8f}
卖出价格: ${current_price:.8f}
收益: {gain:.2f}%""",
                                        )
                                    except Exception as e:
                                        logger.error(f"通知用户 {user_id} 失败: {e}")

                                del self.price_map[ca]
                            except Exception as e:
                                logger.error(f"发送卖出指令失败: {e}")

                        # 止损
                        elif gain <= -stop_loss:
                            try:
                                # 确定发送目标
                                target = (
                                    self.config.get("bot_chat_id", "")
                                    or self.config["bot_username"]
                                )

                                sell_cmd = f"/sell {ca} 100"  # 卖出全部

                                # 记录待处理的卖出交易
                                tx_id = f"sell_{ca}_{int(time.time())}"
                                self.pending_transactions[tx_id] = {
                                    "ca": ca,
                                    "type": "sell",
                                    "user_id": user_id,
                                    "timestamp": time.time(),
                                    "reason": "stop_loss",
                                    "retry_count": 0,  # 初始化重试计数
                                    "max_retries": self.config[
                                        "max_transaction_retries"
                                    ],
                                }

                                await self.client.send_message(target, sell_cmd)
                                logger.info(f"已发送卖出指令(止损): {sell_cmd}")

                                TransactionManager.save_transaction(
                                    ca, "sell", current_price, "100%", user_id
                                )

                                # 如果有用户ID，通知用户
                                if user_id:
                                    try:
                                        await self.client.send_message(
                                            user_id,
                                            f"""止损触发! 已卖出 {ca}
买入价格: ${buy_price:.8f}
卖出价格: ${current_price:.8f}
损失: {gain:.2f}%""",
                                        )
                                    except Exception as e:
                                        logger.error(f"通知用户 {user_id} 失败: {e}")

                                del self.price_map[ca]
                            except Exception as e:
                                logger.error(f"发送卖出指令失败: {e}")
                    else:
                        logger.warning(f"无法获取 {ca} 的当前价格")
            except Exception as e:
                logger.error(f"监控价格时出错: {e}")

            await asyncio.sleep(self.config["price_check_interval"])

    async def start(self):
        """启动机器人"""
        retry_count = 0
        max_retries = 5

        while retry_count < max_retries:
            try:
                self.client = await self.connect_client()

                # 尝试获取交易机器人实体
                try:
                    bot_entity = await self.client.get_entity(
                        self.config["bot_username"]
                    )
                    logger.info(f"已获取交易机器人实体: {bot_entity.id}")
                    # 如果没有设置bot_chat_id，则使用获取到的实体ID
                    if not self.config.get("bot_chat_id"):
                        self.config["bot_chat_id"] = bot_entity.id
                except Exception as e:
                    logger.warning(f"获取交易机器人实体失败: {e}")

                await self.setup_message_handler()
                logger.info("自动交易机器人已启动")

                # 启动价格监控任务
                monitor_task = asyncio.create_task(self.monitor_price())

                # 运行客户端直到断开连接
                await self.client.run_until_disconnected()

                # 如果客户端断开连接，取消监控任务
                monitor_task.cancel()
                logger.warning("客户端断开连接，尝试重新连接...")

            except errors.NetworkError as e:
                retry_count += 1
                wait_time = min(30, 2**retry_count)  # 指数退避策略
                logger.error(
                    f"网络错误: {e}. 将在 {wait_time} 秒后重试. 重试次数: {retry_count}/{max_retries}"
                )
                await asyncio.sleep(wait_time)

            except Exception as e:
                logger.critical(f"发生严重错误: {e}")
                break

        if retry_count >= max_retries:
            logger.critical(f"达到最大重试次数 ({max_retries})，程序终止")


async def main():
    """主函数"""
    try:
        bot = BSCBot()
        await bot.start()
    except Exception as e:
        logger.critical(f"程序启动失败: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
    except Exception as e:
        logger.critical(f"程序崩溃: {e}")
