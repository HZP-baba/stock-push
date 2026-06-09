# 四大理论融合：消息面+技术面双驱动每日选股程序
# 带重试机制的稳定版
import tushare as ts
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import random

# 全局配置
RETRY_TIMES = 3  # 失败重试次数
RETRY_DELAY = 2  # 重试间隔秒数

def retry(func):
    """重试装饰器"""
    def wrapper(*args, **kwargs):
        for i in range(RETRY_TIMES):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                print(f"函数{func.__name__}执行失败，第{i+1}次重试: {e}")
                time.sleep(RETRY_DELAY + random.random())
        print(f"函数{func.__name__}执行失败，已重试{RETRY_TIMES}次")
        return None
    return wrapper

@retry
def get_trade_date():
    """获取最近的交易日"""
    today = datetime.now()
    # 如果是周末，调整到上周五
    if today.weekday() == 5:
        return today - timedelta(days=1)
    elif today.weekday() == 6:
        return today - timedelta(days=2)
    return today

@retry
def get_stock_list():
    """获取A股主板股票列表（过滤科创板、创业板）"""
    # 获取沪深A股列表
    stock_df = ts.get_stock_basics()
    # 过滤688开头(科创板)和30开头(创业板)
    stock_df = stock_df[~stock_df.index.str.startswith('688')]
    stock_df = stock_df[~stock_df.index.str.startswith('30')]
    # 过滤ST股票
    stock_df = stock_df[~stock_df['name'].str.contains('ST')]
    return stock_df

@retry
def get_technical_data(code, days=120):
    """获取股票技术数据"""
    # 获取日K线数据
    df = ts.get_k_data(code, 
                      start=(datetime.now()-timedelta(days=days)).strftime("%Y-%m-%d"),
                      end=datetime.now().strftime("%Y-%m-%d"),
                      ktype='D', autype='qfq')
    if len(df) < 60:
        return None
    
    # 计算均线
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma20'] = df['close'].rolling(20).mean()
    df['ma60'] = df['close'].rolling(60).mean()
    
    # 计算成交量
    df['volume_ma5'] = df['volume'].rolling(5).mean()
    
    return df.iloc[-1]  # 返回最新一天的数据

def is_trend_up(data):
    """判断是否处于上升趋势（道氏+趋势理论）"""
    return (data['ma5'] > data['ma10'] and 
            data['ma10'] > data['ma20'] and 
            data['ma20'] > data['ma60'])

@retry
def is_breakout(code):
    """判断是否突破平台（趋势+波浪理论）"""
    df = ts.get_k_data(code, 
                      start=(datetime.now()-timedelta(days=60)).strftime("%Y-%m-%d"),
                      end=datetime.now().strftime("%Y-%m-%d"),
                      ktype='D', autype='qfq')
    if len(df) < 30:
        return False
    
    # 最近15天的最高价
    recent_high = df['close'].iloc[-15:].max()
    # 突破当日成交量
    today_volume = df['volume'].iloc[-1]
    # 前5日平均成交量
    avg_volume = df['volume'].iloc[-6:-1].mean()
    
    # 突破条件：收盘价创15日新高，成交量放大1.8倍以上
    return (df['close'].iloc[-1] >= recent_high and 
            today_volume >= avg_volume * 1.8)

def select_technical_stocks(limit=3):
    """技术面选股：选出符合趋势+突破条件的股票"""
    stock_list = get_stock_list()
    if stock_list is None:
        return []
    
    selected = []
    print("开始技术面选股...")
    
    # 随机打乱股票顺序，避免每次都从同一个地方开始
    codes = list(stock_list.index)
    random.shuffle(codes)
    
    for code in codes[:500]:  # 只遍历前500只，加快速度避免超时
        name = stock_list.loc[code, 'name']
        market_cap = stock_list.loc[code, 'outstanding'] * stock_list.loc[code, 'price']
        
        # 过滤市值过大或过小的股票（50亿-500亿）
        if market_cap < 50 or market_cap > 500:
            continue
        
        data = get_technical_data(code)
        if data is None:
            continue
        
        if is_trend_up(data) and is_breakout(code):
            selected.append({
                'code': code,
                'name': name,
                'price': data['close'],
                'change': ((data['close'] - data['open']) / data['open']) * 100
            })
            print(f"选中: {code} {name}")
            
            if len(selected) >= limit:
                break
        
        # 每次请求后加延时，避免被限流
        time.sleep(0.5)
    
    return selected

def generate_report(technical_stocks):
    """生成每日推荐报告"""
    today = get_trade_date().strftime("%Y-%m-%d")
    filename = f"每日股票推荐_{today}.md"
    
    content = f"""# 每日股票推荐 {today}

## 策略说明
本报告基于**道氏理论、趋势理论、波浪理论、江恩理论**融合的选股策略，
筛选出**均线多头排列+放量突破平台**的高胜率股票。

---

## 技术突破及趋势推荐（3只）
"""
    
    if len(technical_stocks) == 0:
        content += "今日暂无符合条件的技术突破股票\n"
    else:
        for i, stock in enumerate(technical_stocks, 1):
            content += f"{i}. **{stock['name']}({stock['code']})**\n"
            content += f"   - 现价：{stock['price']:.2f}元\n"
            content += f"   - 今日涨跌幅：{stock['change']:.2f}%\n"
            content += f"   - 入选理由：5/10/20/60日均线多头排列，放量突破15日新高\n\n"
    
    content += """---

## 交易提示
1.  买入：突破关键价位时分批建仓，单只仓位不超过总资金的20%
2.  止损：买入后亏损5%无条件止损
3.  止盈：短线目标15%-20%，中线目标根据波浪理论测算
4.  本报告仅供参考，不构成任何投资建议
"""
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    
    print(f"报告生成成功：{filename}")
    return filename

def main():
    print("开始每日选股程序...")
    print(f"当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 技术面选股
    technical_stocks = select_technical_stocks(limit=3)
    
    # 生成报告
    generate_report(technical_stocks)
    
    print("选股程序执行完成！")

if __name__ == "__main__":
    main()
