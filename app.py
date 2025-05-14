from telethon import TelegramClient, events, errors
import requests
import asyncio
import time
import logging
import json
import os
import yaml
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from telethon.tl.functions.channels import JoinChannelRequest
import re

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


# 从配置文件加载配置
def load_config():
    try:
        if os.path.exists("config.yaml"):
            with open("config.yaml", "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            logger.info("已从config.yaml加载配置")

            # 确保必要的配置项存在
            if "wallet_address" not in config:
                logger.warning("配置中缺少wallet_address参数，将无法验证代币余额")
                config["wallet_address"] = ""

            return config
        else:
            logger.error("配置文件不存在，请创建config.yaml文件")
            raise FileNotFoundError("配置文件不存在")
    except Exception as e:
        logger.error(f"配置加载失败: {e}")
        raise


# 创建带有重试机制的请求会话
def create_request_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


# 全局变量
config = load_config()
price_map = {}
http_session = create_request_session()
pending_transactions = (
    {}
)  # 跟踪待处理的交易 {transaction_id: {"ca": contract_address, "type": "buy/sell", "user_id": user_id, "timestamp": time}}


# 检查用户是否授权
def is_authorized(user_id):
    if "authorized_users" in config and isinstance(config["authorized_users"], list):
        return user_id in config["authorized_users"]
    return False


# 验证合约地址是否存在
def verify_contract(ca):
    try:
        # 首先尝试使用BSCScan API直接验证合约是否存在
        if (
            "bscscan_api_key" in config
            and config["bscscan_api_key"]
            and config["bscscan_api_key"] != "YOUR_BSCSCAN_API_KEY"
        ):
            bsc_url = f"https://api.bscscan.com/api?module=contract&action=getabi&address={ca}&apikey={config['bscscan_api_key']}"
            bsc_response = http_session.get(bsc_url, timeout=10)
            bsc_data = bsc_response.json()

            # 检查合约是否存在
            if (
                bsc_data["status"] == "1"
                or bsc_data["result"] == "Contract source code not verified"
            ):
                logger.info(f"BSCScan API 验证合约 {ca} 存在")
                return True, "合约地址有效"

        # 方法2: 使用DexScreener API验证是否有交易对
        url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"
        response = http_session.get(url, timeout=10)
        data = response.json()
        if "pairs" in data and data["pairs"] and len(data["pairs"]) > 0:
            return True, "合约地址有效"

        # 如果BSCScan API未配置或验证失败，且DexScreener也没有数据，再尝试BSCScan合约代码检查
        if (
            "bscscan_api_key" not in config
            or config["bscscan_api_key"] == "YOUR_BSCSCAN_API_KEY"
            or not config["bscscan_api_key"]
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


# 获取当前 token 的价格（USD）- DexScreener API
def get_price_dexscreener(ca):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"
    try:
        response = http_session.get(url, timeout=10)
        data = response.json()
        if "pairs" in data and data["pairs"] and len(data["pairs"]) > 0:
            return float(data["pairs"][0]["priceUsd"])
        logger.warning(f"获取价格数据格式不正确: {data}")
        return None
    except Exception as e:
        logger.error(f"DexScreener获取价格失败: {e}")
        return None


# 获取当前价格
def get_current_price(ca):
    return get_price_dexscreener(ca)


# 检查钱包中代币余额
def check_token_balance(wallet_address, token_address):
    """
    检查指定钱包地址中某代币的余额
    返回: (bool, str) - (是否有余额, 错误信息或余额)
    """
    try:
        if not wallet_address or not token_address:
            return False, "钱包地址或代币地址为空"

        # 确保有BSCScan API密钥
        if (
            "bscscan_api_key" not in config
            or not config["bscscan_api_key"]
            or config["bscscan_api_key"] == "YOUR_BSCSCAN_API_KEY"
        ):
            return False, "BSCScan API密钥未配置，无法查询链上余额"

        # 使用BSCScan API查询代币余额
        api_url = f"https://api.bscscan.com/api?module=account&action=tokenbalance&contractaddress={token_address}&address={wallet_address}&tag=latest&apikey={config['bscscan_api_key']}"
        response = http_session.get(api_url, timeout=10)
        data = response.json()

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


# 保存交易记录
def save_transaction(ca, action, price, amount=None, user_id=None):
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


# 帮助命令处理函数
async def handle_help_command(event, client):
    help_text = """GMGN自动交易机器人命令:
/join - 加入交易机器人群组或频道
/help - 显示此帮助信息"""
    await client.send_message(event.sender_id, help_text)


# 加入交易机器人群组或频道
async def handle_join_command(event, client):
    try:
        user_id = event.sender_id
        bot_username = config["bot_username"]
        if bot_username.startswith("@"):
            bot_username = bot_username[1:]

        # 尝试加入频道
        try:
            await client(JoinChannelRequest(bot_username))
            await client.send_message(user_id, f"已成功加入 @{bot_username}")
            return
        except Exception as e:
            logger.warning(f"加入频道失败: {e}")

        # 如果不是频道，可能是私人群组或机器人，尝试直接开始对话
        try:
            entity = await client.get_entity(bot_username)
            await client.send_message(entity, "/start")
            await client.send_message(user_id, f"已成功开始与 @{bot_username} 的对话")
            return
        except Exception as e:
            logger.warning(f"开始对话失败: {e}")

        await client.send_message(user_id, "无法加入交易机器人，请手动加入或检查配置")
    except Exception as e:
        logger.error(f"处理加入命令时出错: {e}")
        await client.send_message(user_id, "加入过程中出错，请稍后再试")


# 自动监听合约地址并执行买入
async def setup_message_handler(client):
    @client.on(events.NewMessage)
    async def handler(event):
        try:
            user_id = event.sender_id
            text = event.message.message.strip()

            # 处理命令
            if text.startswith("/"):
                command_parts = text.split()
                command = command_parts[0].lower()

                if command == "/help":
                    await handle_help_command(event, client)
                    return

                if command == "/join":
                    await handle_join_command(event, client)
                    return

            # 处理合约地址，只接受授权用户的消息
            if text.startswith("0x") and len(text) == 42:
                # 检查用户是否授权
                if not is_authorized(user_id):
                    logger.warning(f"未授权用户 {user_id} 尝试发送合约地址: {text}")
                    await client.send_message(user_id, "您没有权限使用此功能")
                    return

                ca = text
                logger.info(f"收到授权用户 {user_id} 的合约地址: {ca}")

                # 验证合约地址是否存在
                is_valid, message = verify_contract(ca)
                if not is_valid:
                    logger.warning(f"无效的合约地址: {ca}, 原因: {message}")
                    await client.send_message(user_id, f"无效的合约地址: {message}")
                    return

                logger.info(f"合约地址验证通过: {ca}")
                await client.send_message(user_id, f"合约地址验证通过，准备买入...")

                # 发送 /buy 指令到交易机器人
                buy_cmd = f"/buy {ca} {config['buy_amount']}"

                # 确定发送目标
                target = config.get("bot_chat_id", "") or config["bot_username"]

                # 记录待处理的买入交易
                tx_id = f"buy_{ca}_{int(time.time())}"
                pending_transactions[tx_id] = {
                    "ca": ca,
                    "type": "buy",
                    "user_id": user_id,
                    "timestamp": time.time(),
                }

                await client.send_message(target, buy_cmd)
                logger.info(f"已发送买入指令: {buy_cmd}")

                # 等待几秒确认交易完成
                await asyncio.sleep(config["buy_confirmation_delay"])

                # 重试获取价格，最多3次
                price = None
                for attempt in range(3):
                    price = get_current_price(ca)
                    if price:
                        break
                    logger.warning(f"获取价格尝试 {attempt+1}/3 失败，重试中...")
                    await asyncio.sleep(2)

                if price:
                    price_map[ca] = {
                        "buy_price": price,
                        "buy_time": time.time(),
                        "take_profit": config["target_gain_percent"],
                        "stop_loss": config["stop_loss_percent"],
                        "user_id": user_id,  # 记录下单用户ID
                    }
                    logger.info(f"用户 {user_id} 买入 {ca} 价格: {price} USD")
                    save_transaction(ca, "buy", price, config["buy_amount"], user_id)

                    await client.send_message(
                        user_id,
                        f"""已买入 {ca}
买入价格: ${price:.8f}
止盈设置: {config["target_gain_percent"]}%
止损设置: {config["stop_loss_percent"]}%
开始监控价格变化...""",
                    )
                else:
                    logger.error(f"无法获取价格，已放弃监控该合约: {ca}")
                    await client.send_message(
                        user_id, "无法获取价格，交易可能已完成但无法监控价格变化"
                    )

        except Exception as e:
            logger.error(f"处理消息时出错: {e}")

    # 监听交易机器人的回复
    @client.on(events.NewMessage(from_users=config["bot_username"]))
    async def bot_response_handler(event):
        try:
            text = event.message.message.strip()
            logger.info(f"收到交易机器人消息: {text}")

            # 检测买入成功的消息
            if "已成功买入" in text or "successfully bought" in text.lower():
                # 尝试从消息中提取合约地址
                contract_match = re.search(r"0x[a-fA-F0-9]{40}", text)
                if contract_match:
                    ca = contract_match.group(0)
                    # 清理相关的待处理交易
                    for tx_id in list(pending_transactions.keys()):
                        if (
                            pending_transactions[tx_id]["ca"] == ca
                            and pending_transactions[tx_id]["type"] == "buy"
                        ):
                            logger.info(f"买入交易 {tx_id} 已成功，从待处理列表中移除")
                            del pending_transactions[tx_id]
                else:
                    logger.warning("检测到买入成功消息，但无法提取合约地址")

            # 检测交易失败的消息
            elif "链上交易失败" in text or "滑点不够" in text:
                logger.warning(f"检测到交易失败消息: {text}")

                # 查找最近的待处理交易
                if pending_transactions:
                    # 按时间戳排序，获取最近的交易
                    sorted_transactions = sorted(
                        pending_transactions.items(),
                        key=lambda x: x[1]["timestamp"],
                        reverse=True,
                    )

                    if sorted_transactions:
                        tx_id, tx_data = sorted_transactions[0]
                        ca = tx_data["ca"]
                        tx_type = tx_data["type"]
                        user_id = tx_data["user_id"]

                        # 从待处理交易中移除
                        del pending_transactions[tx_id]

                        # 如果是卖出交易失败，我们不需要从price_map中删除，因为仍需继续监控
                        # 如果是买入交易失败，检查是否已经添加到price_map中，如果是则移除
                        if tx_type == "buy" and ca in price_map:
                            del price_map[ca]
                            logger.info(f"由于买入失败，已停止监控合约 {ca}")

                        if user_id:
                            try:
                                # 通知用户交易失败
                                failure_message = f"警告: {tx_type}合约 {ca} 的交易失败，原因: {text}\n"
                                if tx_type == "buy":
                                    failure_message += "请检查滑点设置或稍后重试。"
                                else:  # sell
                                    failure_message += "卖出失败，将继续监控价格变化。请手动检查或稍后重试卖出。"

                                await client.send_message(user_id, failure_message)
                                logger.info(f"已通知用户 {user_id} 交易失败")
                            except Exception as e:
                                logger.error(f"通知用户 {user_id} 失败: {e}")
                    else:
                        logger.warning("检测到交易失败消息，但没有找到最近的待处理交易")
                else:
                    # 备用方案：尝试从最近的监控列表中找
                    recent_contracts = list(price_map.keys())
                    if recent_contracts:
                        # 获取最近添加的合约（假设是当前操作的合约）
                        latest_contract = recent_contracts[-1]
                        user_id = price_map[latest_contract].get("user_id")

                        if user_id:
                            try:
                                # 通知用户交易失败
                                await client.send_message(
                                    user_id,
                                    f"警告: 合约 {latest_contract} 的交易失败，原因: {text}\n请手动检查交易状态或重试。",
                                )
                                logger.info(f"已通知用户 {user_id} 交易失败")
                            except Exception as e:
                                logger.error(f"通知用户 {user_id} 失败: {e}")
                    else:
                        logger.warning("检测到交易失败消息，但无法确定相关合约地址")

            # 检测卖出成功的消息
            elif "已成功卖出" in text or "successfully sold" in text.lower():
                # 尝试从消息中提取合约地址
                contract_match = re.search(r"0x[a-fA-F0-9]{40}", text)
                if contract_match:
                    ca = contract_match.group(0)

                    # 清理相关的待处理交易
                    for tx_id in list(pending_transactions.keys()):
                        if (
                            pending_transactions[tx_id]["ca"] == ca
                            and pending_transactions[tx_id]["type"] == "sell"
                        ):
                            logger.info(f"卖出交易 {tx_id} 已成功，从待处理列表中移除")
                            del pending_transactions[tx_id]

                    if ca in price_map:
                        logger.info(f"检测到合约 {ca} 已成功卖出，停止监控")

                        # 如果配置了钱包地址，验证链上余额
                        if config["wallet_address"]:
                            has_balance, message = check_token_balance(
                                config["wallet_address"], ca
                            )
                            if has_balance:
                                logger.warning(
                                    f"链上检测到仍持有代币: {message}，继续监控"
                                )
                                # 通知用户但继续监控
                                user_id = price_map[ca].get("user_id")
                                if user_id:
                                    try:
                                        await client.send_message(
                                            user_id,
                                            f"警告: 交易机器人报告卖出成功，但链上检测到仍持有代币 {ca}，继续监控价格变化",
                                        )
                                    except Exception as e:
                                        logger.error(f"通知用户 {user_id} 失败: {e}")
                                return

                        # 如果没有配置钱包地址或链上余额为0，停止监控
                        # 如果有用户ID，通知用户
                        user_id = price_map[ca].get("user_id")
                        if user_id:
                            try:
                                await client.send_message(
                                    user_id,
                                    f"检测到合约 {ca} 已成功卖出，停止监控价格变化",
                                )
                            except Exception as e:
                                logger.error(f"通知用户 {user_id} 失败: {e}")

                        # 从监控列表中移除
                        del price_map[ca]
                    else:
                        logger.warning(f"检测到合约 {ca} 卖出成功，但不在监控列表中")
                else:
                    logger.warning("检测到卖出成功消息，但无法提取合约地址")

        except Exception as e:
            logger.error(f"处理交易机器人消息时出错: {e}")


# 清理过期的待处理交易
def cleanup_pending_transactions():
    """清理超过5分钟的待处理交易"""
    current_time = time.time()
    expired_threshold = 300  # 5分钟

    for tx_id in list(pending_transactions.keys()):
        tx_data = pending_transactions[tx_id]
        if current_time - tx_data["timestamp"] > expired_threshold:
            logger.warning(f"交易 {tx_id} 已超过5分钟未确认，从待处理列表中移除")
            del pending_transactions[tx_id]


# 定时检查价格是否达到目标涨幅或止损点
async def monitor_price(client):
    while True:
        try:
            # 清理过期的待处理交易
            cleanup_pending_transactions()

            for ca, data in list(price_map.items()):
                buy_price = data["buy_price"]
                take_profit = data["take_profit"]
                stop_loss = data["stop_loss"]
                user_id = data.get("user_id")  # 获取用户ID

                # 如果配置了钱包地址，先检查链上余额是否为0（可能已经卖出）
                if config["wallet_address"]:
                    has_balance, message = check_token_balance(
                        config["wallet_address"], ca
                    )
                    if not has_balance:
                        logger.info(f"链上检测到合约 {ca} 已卖出 ({message})，停止监控")

                        # 如果有用户ID，通知用户
                        if user_id:
                            try:
                                await client.send_message(
                                    user_id,
                                    f"链上检测到合约 {ca} 已卖出，停止监控价格变化",
                                )
                            except Exception as e:
                                logger.error(f"通知用户 {user_id} 失败: {e}")

                        # 从监控列表中移除
                        del price_map[ca]
                        continue

                current_price = get_current_price(ca)

                if current_price:
                    gain = ((current_price - buy_price) / buy_price) * 100
                    logger.info(f"合约 {ca} 当前涨幅: {gain:.2f}%")

                    # 止盈
                    if gain >= take_profit:
                        try:
                            # 确定发送目标
                            target = (
                                config.get("bot_chat_id", "") or config["bot_username"]
                            )

                            sell_cmd = f"/sell {ca} 100"  # 卖出全部

                            # 记录待处理的卖出交易
                            tx_id = f"sell_{ca}_{int(time.time())}"
                            pending_transactions[tx_id] = {
                                "ca": ca,
                                "type": "sell",
                                "user_id": user_id,
                                "timestamp": time.time(),
                                "reason": "take_profit",
                            }

                            await client.send_message(target, sell_cmd)
                            logger.info(f"已发送卖出指令(止盈): {sell_cmd}")

                            save_transaction(ca, "sell", current_price, "100%", user_id)

                            # 如果有用户ID，通知用户
                            if user_id:
                                try:
                                    await client.send_message(
                                        user_id,
                                        f"""止盈触发! 已卖出 {ca}
买入价格: ${buy_price:.8f}
卖出价格: ${current_price:.8f}
收益: {gain:.2f}%""",
                                    )
                                except Exception as e:
                                    logger.error(f"通知用户 {user_id} 失败: {e}")

                            del price_map[ca]
                        except Exception as e:
                            logger.error(f"发送卖出指令失败: {e}")

                    # 止损
                    elif gain <= -stop_loss:
                        try:
                            # 确定发送目标
                            target = (
                                config.get("bot_chat_id", "") or config["bot_username"]
                            )

                            sell_cmd = f"/sell {ca} 100"  # 卖出全部

                            # 记录待处理的卖出交易
                            tx_id = f"sell_{ca}_{int(time.time())}"
                            pending_transactions[tx_id] = {
                                "ca": ca,
                                "type": "sell",
                                "user_id": user_id,
                                "timestamp": time.time(),
                                "reason": "stop_loss",
                            }

                            await client.send_message(target, sell_cmd)
                            logger.info(f"已发送卖出指令(止损): {sell_cmd}")

                            save_transaction(ca, "sell", current_price, "100%", user_id)

                            # 如果有用户ID，通知用户
                            if user_id:
                                try:
                                    await client.send_message(
                                        user_id,
                                        f"""止损触发! 已卖出 {ca}
买入价格: ${buy_price:.8f}
卖出价格: ${current_price:.8f}
损失: {gain:.2f}%""",
                                    )
                                except Exception as e:
                                    logger.error(f"通知用户 {user_id} 失败: {e}")

                            del price_map[ca]
                        except Exception as e:
                            logger.error(f"发送卖出指令失败: {e}")
                else:
                    logger.warning(f"无法获取 {ca} 的当前价格")
        except Exception as e:
            logger.error(f"监控价格时出错: {e}")

        await asyncio.sleep(config["price_check_interval"])


# 连接到Telegram客户端，包含重连逻辑
async def connect_client():
    # 使用用户账号登录
    client = TelegramClient("bsc", config["api_id"], config["api_hash"])

    try:
        # 如果配置了电话号码，则使用电话号码登录
        if "phone" in config and config["phone"]:
            await client.start(phone=config["phone"])
        else:
            # 否则使用交互式登录
            await client.start()

        logger.info("成功以用户身份登录Telegram")
        return client
    except Exception as e:
        logger.error(f"连接Telegram失败: {e}")
        raise


async def main():
    retry_count = 0
    max_retries = 5

    while retry_count < max_retries:
        try:
            client = await connect_client()

            # 尝试获取交易机器人实体
            try:
                bot_entity = await client.get_entity(config["bot_username"])
                logger.info(f"已获取交易机器人实体: {bot_entity.id}")
                # 如果没有设置bot_chat_id，则使用获取到的实体ID
                if not config.get("bot_chat_id"):
                    config["bot_chat_id"] = bot_entity.id
            except Exception as e:
                logger.warning(f"获取交易机器人实体失败: {e}")

            await setup_message_handler(client)
            logger.info("自动交易机器人已启动")

            # 启动价格监控任务
            monitor_task = asyncio.create_task(monitor_price(client))

            # 运行客户端直到断开连接
            await client.run_until_disconnected()

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


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
    except Exception as e:
        logger.critical(f"程序崩溃: {e}")
