import os  # 读取环境变量，例如 API key

import ccxt  # 使用 ccxt 连接 Binance 等交易所

from config import BINANCE_TESTNET_ENV  # 导入测试网环境变量名


def create_exchange() -> ccxt.binance:  # 定义函数：创建 Binance 交易所对象
    exchange = ccxt.binance(  # 初始化 ccxt 的 Binance 客户端
        {  # ccxt 初始化参数字典开始
            "apiKey": os.getenv("BINANCE_API_KEY", ""),  # 从环境变量读取 API Key，没有就用空字符串
            "secret": os.getenv("BINANCE_API_SECRET", ""),  # 从环境变量读取 API Secret，没有就用空字符串
            "enableRateLimit": True,  # 启用 ccxt 内置限速，减少触发交易所频率限制的风险
            "options": {  # Binance 的额外配置项开始
                "defaultType": "future",  # 指定默认市场类型为合约，而不是现货
                "adjustForTimeDifference": True,  # 自动校准本地时间和交易所服务器时间差
                "fetchCurrencies": False,  # 避免 load_markets 触发现货资金配置接口
                "fetchMarkets": {"types": ["linear"]},  # 只加载 USDT 本位合约市场，避免拉取现货或杠杆市场
            },  # Binance 额外配置项结束
        }  # ccxt 初始化参数字典结束
    )  # Binance 客户端初始化完成
    if os.getenv(BINANCE_TESTNET_ENV, "").lower() == "true":  # 如果环境变量要求使用 Binance 测试网
        # testnet_rest_base = "https://testnet.binancefuture.com/fapi/v1"  # Binance USDT 本位合约测试网 REST 基础地址
        # exchange.urls["api"]["fapiPublic"] = testnet_rest_base  # 切换合约公共 REST 接口到测试网
        # exchange.urls["api"]["fapiPrivate"] = testnet_rest_base  # 切换合约私有 REST 接口到测试网
        # exchange.urls["api"]["fapiPublicV2"] = testnet_rest_base  # 兼容部分 ccxt 版本的 V2 公共接口
        # exchange.urls["api"]["fapiPrivateV2"] = testnet_rest_base  # 兼容部分 ccxt 版本的 V2 私有接口
        # print("[EXCHANGE] Binance futures testnet REST endpoints enabled")  # 打印测试网模式提示
        testnet_api_base = "https://testnet.binancefuture.com/fapi"  # Binance USDT 本位合约测试网 REST 基础地址
        exchange.urls["api"]["fapiPublic"] = f"{testnet_api_base}/v1"  # 切换合约公共 REST v1 接口到测试网
        exchange.urls["api"]["fapiPublicV2"] = f"{testnet_api_base}/v2"  # 切换合约公共 REST v2 接口到测试网
        exchange.urls["api"]["fapiPublicV3"] = f"{testnet_api_base}/v3"  # 切换合约公共 REST v3 接口到测试网
        exchange.urls["api"]["fapiPrivate"] = f"{testnet_api_base}/v1"  # 切换合约私有 REST v1 接口到测试网
        exchange.urls["api"]["fapiPrivateV2"] = f"{testnet_api_base}/v2"  # 切换合约私有 REST v2 接口到测试网
        exchange.urls["api"]["fapiPrivateV3"] = f"{testnet_api_base}/v3"  # 切换合约私有 REST v3 接口到测试网
    return exchange  # 返回创建好的交易所对象
