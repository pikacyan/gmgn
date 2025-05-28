# GMGN 智能交易机器人

基于Telegram的BSC智能交易机器人，自动监控合约地址并执行交易。

## 🚀 核心功能

- **自动交易**：接收合约地址后自动验证并买入
- **智能监控**：实时监控价格变化，自动止盈止损
- **安全验证**：多重合约验证，防止无效合约
- **用户授权**：只允许授权用户操作
- **余额检查**：链上余额验证确认交易状态

## 📋 安装要求

- Python 3.7+
- Telegram账号
- BSCScan API密钥（推荐）
- BNB余额用于交易

## 🛠️ 安装步骤

```bash
git clone https://github.com/yourusername/gmgn.git
cd gmgn
pip install -r requirements.txt
cp config.yaml.example config.yaml
# 编辑config.yaml文件
```

## ⚙️ 配置说明

```yaml
# Telegram API配置
api_id: YOUR_API_ID
api_hash: "YOUR_API_HASH"
phone: "+1234567890"

# 交易机器人配置
bot_username: "trading_bot_username"
wallet_address: "0x..."

# 交易参数
buy_amount: "0.01"  # BNB
target_gain_percent: 50  # 止盈%
stop_loss_percent: 10   # 止损%

# 授权用户
authorized_users:
  - 123456789

# API密钥
bscscan_api_key: "YOUR_BSCSCAN_API_KEY"
```

## 🚀 使用方法

1. **启动机器人**
```bash
python app.py
```

2. **发送合约地址**：直接发送42位合约地址（0x开头）
3. **自动交易**：机器人自动验证、买入并监控价格
4. **自动卖出**：达到止盈或止损条件时自动卖出

## 📊 监控

- **日志文件**：`gmgn_bot.log`
- **交易记录**：`transactions.json`

## ⚠️ 注意事项

- 使用Userbot可能违反Telegram服务条款
- 加密货币交易存在高风险
- 确保配置正确，定期检查运行状态
- 妥善保管API密钥

## 🛠️ 故障排除

1. **连接失败**：检查API ID/Hash和网络连接
2. **合约验证失败**：检查BSCScan API密钥
3. **交易失败**：检查BNB余额和机器人配置
4. **价格获取失败**：检查网络和合约交易对

## ⚠️ 免责声明

本软件仅供学习研究使用。使用本软件进行实际交易的风险由用户自行承担。
