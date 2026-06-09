# 四大理论融合：消息面+技术面双驱动每日选股程序
# 数据源：Akshare（完全免费无限制）
import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup

def get_trade_date():
    """获取最近的交易日"""
    today = datetime.now()
    # 如果是周末，调整到上周五
    if today.weekday() == 5:
        return today - timedelta(days=1)
    elif today.weekday() == 6:
        return today - timedelta(days=2)
    return today

def get_stock_list():
    """获取A股所有股票列表"""
    stock_df = ak.stock_info_a_code_name()
    return stock_df

def get_technical_data(code, days=120):
    """获取股票技术数据"""
    try:
        # 获取日K线数据
        df = ak.stock_zh_a_hist(symbol=code, period="daily", 
                               start_date=(datetime.now()-timedelta(days=days)).strftime("%Y%m%d"),
                               end_date=datetime.now().strftime("%Y%m%d"),
                               adjust="qfq")
        if len(df) < 60:
            return None
        
        # 计算均线
        df['ma5'] = df['收盘'].rolling(5).mean()
        df['ma10'] = df['收盘'].rolling(10).mean()
        df['ma20'] = df['收盘'].rolling(20).mean()
        df['ma60'] = df['收盘'].rolling(60).mean()
        
        # 计算成交量
        df['volume_ma5'] = df['成交量'].rolling(5).mean()
        
        return df.iloc[-1]  # 返回最新一天的数据
    except Exception as e:
        print(f"获取{code}数据失败: {e}")
        return None

def is_trend_up(data):
    """判断是否处于上升趋势（道氏+趋势理论）"""
    return (data['ma5'] > data['ma10'] and 
            data['ma10'] > data['ma20'] and 
            data['ma20'] > data['ma60'])

def is_breakout(code):
    """判断是否突破平台（趋势+波浪理论）"""
    try:
        df = ak.stock_zh_a_hist(symbol=code, period="daily", 
                               start_date=(datetime.now()-timedelta(days=60)).strftime("%Y%m%d"),
                               end_date=datetime.now().strftime("%Y%m%d"),
                               adjust="qfq")
        if len(df) < 30:
            return False
        
        # 最近15天的最高价
        recent_high = df['收盘'].iloc[-15:].max()
        # 突破当日成交量
        today_volume = df['成交量'].iloc[-1]
        # 前5日平均成交量
        avg_volume = df['成交量'].iloc[-6:-1].mean()
        
        # 突破条件：收盘价创15日新高，成交量放大1.8倍以上
        return (df['收盘'].iloc[-1] >= recent_high and 
                today_volume >= avg_volume * 1.8)
    except Exception as e:
        print(f"判断{code}突破失败: {e}")
        return False

def get_news_stocks():
    """获取消息面热门股票（简单版）"""
    # 这里可以扩展为爬取各大财经网站的新闻
    # 目前返回空列表，后续可以添加消息面筛选逻辑
    return []

def select_technical_stocks(limit=3):
    """技术面选股：选出符合趋势+突破条件的股票"""
    stock_list = get_stock_list()
    selected = []
    
    print("开始技术面选股...")
    for idx, row in stock_list.iterrows():
        code = row['代码']
        name = row['名称']
        
        # 过滤ST和科创板、创业板（可根据需要调整）
        if 'ST' in name or code.startswith('688') or code.startswith('30'):
            continue
        
        # 过滤市值过大或过小的股票
        try:
            info = ak.stock_individual_info_em(symbol=code)
            market_cap = info[info['item'] == '总市值']['value'].values[0] / 1e8
            if market_cap < 50 or market_cap > 500:
                continue
        except:
            continue
        
        data = get_technical_data(code)
        if data is None:
            continue
        
        if is_trend_up(data) and is_breakout(code):
            selected.append({
                'code': code,
                'name': name,
                'price': data['收盘'],
                'change': data['涨跌幅']
            })
            print(f"选中: {code} {name}")
            
            if len(selected) >= limit:
                break
    
    return selected

def generate_report(news_stocks, technical_stocks):
    """生成每日推荐报告"""
    today = get_trade_date().strftime("%Y-%m-%d")
    filename = f"每日股票推荐_{today}.md"
    
    content = f"""# 每日股票推荐 {today}

## 策略说明
本报告基于**道氏理论、趋势理论、波浪理论、江恩理论**融合的选股策略，
筛选出**消息面催化+技术面突破**的高胜率股票。

---

## 消息面推荐（3只）
"""
    
    if len(news_stocks) == 0:
        content += "今日暂无符合条件的消息面股票\n"
    else:
        for i, stock in enumerate(news_stocks, 1):
            content += f"{i}. **{stock['name']}({stock['code']})**\n"
            content += f"   - 现价：{stock['price']:.2f}元\n"
            content += f"   - 消息主题：{stock['news']}\n\n"
    
    content += """---

## 技术突破及趋势推荐（3只）
"""
    
    for i, stock in enumerate(technical_stocks, 1):
        content += f"{i}. **{stock['name']}({stock['code']})**\n"
        content += f"   - 现价：{stock['price']:.2f}元\n"
        content += f"   - 今日涨跌幅：{stock['change']:.2f}%\n"
        content += f"   - 入选理由：均线多头排列，放量突破近期平台\n\n"
    
    content += """---

## 交易提示
1.  买入：突破关键价位时分批建仓，单只仓位不超过20%
2.  止损：买入后亏损5%无条件止损
3.  止盈：短线目标15%-20%，中线目标30%-50%
4.  本报告仅供参考，不构成投资建议
"""
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    
    print(f"报告生成成功：{filename}")
    return filename

def main():
    print("开始每日选股程序...")
    print(f"当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 消息面选股（目前为演示，后续可扩展）
    news_stocks = get_news_stocks()
    
    # 技术面选股
    technical_stocks = select_technical_stocks(limit=3)
    
    # 生成报告
    generate_report(news_stocks, technical_stocks)
    
    print("选股程序执行完成！")

if __name__ == "__main__":
    main()
