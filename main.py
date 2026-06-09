import tushare as ts
import pandas as pd
import numpy as np
import requests
import os
from datetime import datetime, timedelta

# ---------- 配置区 ----------
TUSHARE_TOKEN = "15f4ff96a5ef17935a8d7a837ad5054378fb17018631b54ff3d6ec1e"      # 替换成你刚复制的token
PUSHPLUS_TOKEN = "669483919ae44d5599737f6c1b6b98fd"    # 替换成你刚复制的token

ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

# ---------- 工具函数 ----------
def get_all_stocks():
    """获取所有A股股票列表"""
    data = pro.stock_basic(exchange='', list_status='L', 
                           fields='ts_code,symbol,name,area,industry,list_date')
    return data

def get_daily(ts_code, start_date, end_date):
    """获取日线数据"""
    df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
    return df

def get_adj_factor(ts_code, start_date, end_date):
    """获取复权因子"""
    df = pro.adj_factor(ts_code=ts_code, start_date=start_date, end_date=end_date)
    return df

def get_daily_basic(ts_code, trade_date):
    """获取当日指标（包括总市值、流通市值）"""
    df = pro.daily_basic(ts_code=ts_code, trade_date=trade_date,
                         fields='ts_code,trade_date,total_mv,circ_mv,volume_ratio')
    return df

def get_disclosure(trade_date):
    """获取当天的公告（用于消息面筛选）"""
    # 获取最新的临时公告
    df = pro.disclosure_detail(ann_date=trade_date, 
                               fields='ts_code,ann_date,title,type')
    return df

def calculate_ma(df, windows=[5,10,20,60,250]):
    """计算多周期均线"""
    df = df.sort_values('trade_date')
    for w in windows:
        df[f'ma{w}'] = df['close'].rolling(window=w).mean()
    return df

def check_dow_trend(df):
    """道氏理论：站上年线且年线向上"""
    if len(df) < 250:
        return False
    close = df['close'].values[-1]
    ma250 = df['ma250'].values[-1]
    ma250_prev = df['ma250'].values[-5]  # 5天前的年线
    return close > ma250 and ma250 > ma250_prev

def check_trend(df):
    """趋势理论：5/10/20多头排列，或放量突破下降趋势线"""
    if len(df) < 60:
        return False
    # 多头排列
    ma5 = df['ma5'].values[-1]
    ma10 = df['ma10'].values[-1]
    ma20 = df['ma20'].values[-1]
    ma60 = df['ma60'].values[-1]
    bull_align = (ma5 > ma10 > ma20) and (ma60 > df['ma60'].values[-2])
    # 放量突破简单处理：今日收盘价创20日新高且量能放大
    high_20 = df['high'].rolling(20).max().values[-2]  # 昨天为止的20日高点
    vol_today = df['vol'].values[-1]
    vol_ma20 = df['vol'].rolling(20).mean().values[-1]
    breakout = (df['close'].values[-1] > high_20) and (vol_today > vol_ma20 * 1.5)
    return bull_align or breakout

def check_wave(df):
    """简化的波浪理论：判断是否处于3浪或5浪初（通过ZigZag识别趋势高低点）"""
    if len(df) < 30:
        return False
    # 寻找最近的高低点（简单方法：用20天极值）
    high_points = []
    low_points = []
    close = df['close'].values
    for i in range(20, len(close)-5):
        if close[i] == max(close[i-20:i+20]):
            high_points.append((i, close[i]))
        if close[i] == min(close[i-20:i+20]):
            low_points.append((i, close[i]))
    if len(low_points) < 2 or len(high_points) < 2:
        return False
    # 判断是否突破前高（1浪顶）
    prev_high = high_points[-2][1] if len(high_points)>=2 else 0
    last_close = close[-1]
    # 且当前MACD处于零轴上方
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    if last_close > prev_high and macd.values[-1] > 0:
        return True
    return False

def check_gann(df):
    """江恩理论简化：价格突破下降1x1线（从近期高点向下每天降一定幅度）"""
    if len(df) < 30:
        return False
    high_30 = df['high'].rolling(30).max().values[-31]  # 30天前的高点
    # 1x1角度线：每天下降1单位（价格），这里用每日下跌固定值
    days = len(df) - df['high'].rolling(30).idxmax()
    angle_line = high_30 - days  # 简单模型
    last_close = df['close'].values[-1]
    return last_close > angle_line

# ---------- 主逻辑 ----------
def run():
    today = datetime.now().strftime('%Y%m%d')
    trade_date = pro.trade_cal(exchange='SSE', start_date=today, end_date=today)
    if trade_date['is_open'].values[0] == 0:
        print("今天不是交易日，不推送")
        return

    # 获取昨日交易日期（因为我们是盘前运行，实际用的是前一日收盘数据）
    cal = pro.trade_cal(exchange='SSE', start_date='20200101', end_date=today)
    cal = cal[cal['is_open']==1]
    last_trade_date = cal['cal_date'].values[-2] if cal['cal_date'].values[-1]==today else cal['cal_date'].values[-1]
    start_date = (datetime.strptime(last_trade_date, '%Y%m%d') - timedelta(days=365)).strftime('%Y%m%d')

    # 1. 获取所有正常上市股票
    stocks = get_all_stocks()
    # 过滤掉ST、新股（上市小于60天）
    stocks = stocks[~stocks['name'].str.contains('ST')]
    # 流通市值过滤在后续

    # 2. 消息面候选：获取当天公告
    try:
        dis = get_disclosure(last_trade_date)
        if dis is not None and len(dis) > 0:
            # 定义利好的关键词
            good_keywords = ['中标', '签订合同', '业绩预增', '重大合同', '获得订单', 
                             '项目投产', '新产品', '专利', '批复', '股权激励', '增持']
            pattern = '|'.join(good_keywords)
            good_news = dis[dis['title'].str.contains(pattern, na=False)]
            news_codes = good_news['ts_code'].unique()
        else:
            news_codes = []
    except:
        news_codes = []

    # 3. 技术面候选：全部股票遍历（为节省时间，这里只遍历市值前800的股票）
    # 也可以只遍历中证500或你感兴趣的板块
    stock_list = stocks['ts_code'].tolist()
    # 使用市值前800作为遍历池，避免超时
    try:
        mv_df = pro.daily_basic(trade_date=last_trade_date, 
                                fields='ts_code,circ_mv')
        mv_df = mv_df.sort_values('circ_mv', ascending=False).head(800)
        stock_list = mv_df['ts_code'].tolist()
    except:
        pass

    msg_results = []
    tech_results = []

    for ts_code in stock_list:
        try:
            df = get_daily(ts_code, start_date, last_trade_date)
            if len(df) < 60:
                continue
            df = calculate_ma(df)
            last_close = df['close'].values[-1]
            # 道氏
            dow_ok = check_dow_trend(df)
            if not dow_ok:
                continue

            # 趋势
            trend_ok = check_trend(df)
            if not trend_ok:
                continue

            # 先判断技术突破共振（四合一）
            wave_ok = check_wave(df)
            gann_ok = check_gann(df)
            if wave_ok and gann_ok:  # 至少趋势+道氏已过，现再加波浪和江恩
                tech_results.append({
                    'ts_code': ts_code,
                    'name': stocks[stocks['ts_code']==ts_code]['name'].values[0],
                    'close': last_close,
                    'reason': '道趋势波浪江恩共振'
                })
            
            # 再判断消息面
            if ts_code in news_codes:
                # 要求也是趋势通过的
                msg_results.append({
                    'ts_code': ts_code,
                    'name': stocks[stocks['ts_code']==ts_code]['name'].values[0],
                    'close': last_close,
                    'reason': '有利好公告+趋势配合'
                })
        except Exception as e:
            continue

    # 各取前3
    tech_pick = tech_results[:3] if len(tech_results) >= 3 else tech_results
    msg_pick = msg_results[:3] if len(msg_results) >= 3 else msg_results

    # 如果消息面不足，放宽趋势条件再补（从公告中选趋势相对好的）
    if len(msg_pick) < 3 and len(news_codes) > 0:
        for code in news_codes:
            if code not in [m['ts_code'] for m in msg_pick]:
                try:
                    df = get_daily(code, start_date, last_trade_date)
                    if len(df) < 20:
                        continue
                    df = calculate_ma(df)
                    if check_trend(df):
                        msg_pick.append({
                            'ts_code': code,
                            'name': stocks[stocks['ts_code']==code]['name'].values[0],
                            'close': df['close'].values[-1],
                            'reason': '利好公告，趋势尚可'
                        })
                    if len(msg_pick) >= 3:
                        break
                except:
                    pass

    # 生成推送文本
    content = f"【{last_trade_date}收盘后选股，今日盘前推送】\n\n"
    content += "📈 消息面三只股（利好公告+趋势向上）：\n"
    if msg_pick:
        for i, s in enumerate(msg_pick, 1):
            content += f"{i}. {s['name']}({s['ts_code']}) 价格:{s['close']:.2f} 理由:{s['reason']}\n"
    else:
        content += "今日无符合条件的消息面股。\n"

    content += "\n📊 技术突破三只股（道·趋势·波浪·江恩共振）：\n"
    if tech_pick:
        for i, s in enumerate(tech_pick, 1):
            content += f"{i}. {s['name']}({s['ts_code']}) 价格:{s['close']:.2f} 理由:{s['reason']}\n"
    else:
        content += "今日无完全共振的技术突破股。\n"

    content += "\n⚠️ 仅供学习参考，不构成投资建议。股市有风险，投资需谨慎。"

    # 通过PushPlus推送
    url = 'http://www.pushplus.plus/send'
    data = {
        'token': PUSHPLUS_TOKEN,
        'title': f'每日选股推送 {last_trade_date}',
        'content': content,
        'template': 'txt'
    }
    requests.post(url, data=data)
    print("推送完成")

if __name__ == "__main__":
    run()
