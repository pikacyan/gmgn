# GMGN 自动交易机器人

这是一个基于Telegram的自动交易机器人，使用用户账号(Userbot)登录，用于监控特定用户发送的合约地址，并自动执行买入和卖出操作。

## 功能特点

- 使用用户账号(Userbot)登录Telegram
- 用户身份验证和授权管理
- 自动监听指定Telegram用户发送的合约地址
- 验证合约地址有效性，防止买入无效合约
- 自动发送买入指令到交易机器人
- 实时监控代币价格变化
- 支持止盈和止损设置
- 完整的错误处理和日志记录
- 自动重连和故障恢复
- 交易记录保存

## 安装要求

- Python 3.7+
- Telethon
- Requests

## 安装步骤

1. 克隆仓库
```
git clone https://github.com/yourusername/gmgn.git
cd gmgn
```

2. 安装依赖
```
pip install -r requirements.txt
```

3. 配置
创建或编辑 `config.yaml` 文件，填入必要的配置信息。

## 配置说明

通过 `config.yaml` 文件配置机器人，示例如下：

```yaml
# Telegram API配置
api_id: 12345  # 从 https://my.telegram.org 获取
api_hash: "your_api_hash_here"  # 从 https://my.telegram.org 获取
phone: "+1234567890"  # 用于登录的电话号码

# 交易机器人配置
bot_username: "trading_bot_username"  # 交易机器人的用户名
bot_chat_id: 123456789  # 交易机器人的聊天ID（可选）

# 钱包配置
wallet_address: "0x1234567890abcdef1234567890abcdef12345678"  # 用于交易的钱包地址，用于验证代币余额

# 交易参数
buy_amount: "0.01"  # 买入金额（单位：BNB）
target_gain_percent: 50  # 止盈百分比，达到后自动卖出
stop_loss_percent: 10  # 止损百分比，达到后自动卖出

# 系统参数
price_check_interval: 30  # 检查价格的间隔（秒）
buy_confirmation_delay: 5  # 买入后等待确认的时间（秒）

# 授权用户ID列表，只接受以下用户的ca输入
authorized_users:  # 用户ID可以通过 @userinfobot 获取
  - 123456789
  - 987654321

# BSCScan API密钥，用于验证合约地址
bscscan_api_key: "YOUR_BSCSCAN_API_KEY"  # 从 https://bscscan.com/myapikey 获取
```

配置项说明：

- `api_id`：Telegram API ID
- `api_hash`：Telegram API Hash
- `phone`：用于登录的电话号码（格式如：+1234567890）
- `bot_username`：交易机器人的用户名
- `bot_chat_id`：交易机器人的聊天ID（可选）
- `wallet_address`：用于交易的钱包地址，用于验证代币余额（可选，但强烈建议设置）
- `buy_amount`：默认买入金额（单位：BNB）
- `target_gain_percent`：止盈百分比，达到后自动卖出
- `stop_loss_percent`：止损百分比，达到后自动卖出
- `price_check_interval`：检查价格的间隔（秒）
- `buy_confirmation_delay`：买入后等待确认的时间（秒）
- `authorized_users`：授权用户ID列表，只有这些用户可以使用机器人
- `bscscan_api_key`：BSCScan API密钥，用于验证合约地址和代币余额（可选，但强烈建议设置）

## 用户命令

机器人支持以下命令：

- `/join` - 加入交易机器人群组或频道
- `/help` - 显示帮助信息

## 使用方法

1. 启动机器人
```
python app.py
```

2. 首次启动时，会要求你输入验证码或进行其他Telegram身份验证

3. 使用 `/join` 命令加入交易机器人的群组或频道

4. 直接发送合约地址（0x开头的42位地址）给机器人，它会自动验证合约地址，然后买入并开始监控价格变化

5. 当达到止盈或止损点时，机器人会自动卖出并通知你

## 合约地址验证

机器人会在买入前验证合约地址的有效性，验证方式包括：

1. 首先使用BSCScan API检查合约是否存在（需要配置有效的BSCScan API密钥）
2. 使用DexScreener API检查是否存在交易对

这种双重验证机制可以有效防止买入无效合约或诈骗合约，同时也能识别新发布但尚未有交易对的合约。

**重要提示**：强烈建议配置有效的BSCScan API密钥，否则对于新发布或尚未在DEX上有交易对的合约可能无法正确验证。

## 链上余额验证

机器人会通过以下方式验证代币是否已经卖出：

1. 监听交易机器人的卖出成功消息
2. 定期检查钱包中的代币余额

当检测到代币已卖出（余额为0）时，机器人会自动停止监控该合约的价格变化。这可以避免在代币已经卖出后继续不必要的监控。

**注意**：要使用链上余额验证功能，必须在配置文件中设置有效的`wallet_address`和`bscscan_api_key`。

## 日志

日志文件保存在 `gmgn_bot.log`，同时也会输出到控制台。

## 交易记录

所有交易记录会保存在 `transactions.json` 文件中，每笔交易一行，包含时间戳、用户ID、合约地址、操作类型、价格和数量等信息。

## 注意事项

- 使用用户账号(Userbot)可能违反Telegram服务条款，请谨慎使用
- 首次运行时需要进行Telegram账号验证
- 确保API ID和API Hash正确
- 确保有足够的BNB余额进行交易
- 定期检查日志文件，确保机器人正常运行
- 只有被授权的用户才能使用机器人
