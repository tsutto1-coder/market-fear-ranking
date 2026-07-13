"""
市場恐怖度 売られすぎランキング 画像生成スクリプト
GitHub Actions から毎日 18:00 JST に実行される。
生成した画像を ranking_YYYY-MM-DD.jpg として保存する。
GitHub Actions の Artifacts からダウンロードできる。

必要な環境変数（GitHub Secrets に登録）:
  ANTHROPIC_API_KEY … Claude API キー（これだけでOK）
"""

import os, io, json, datetime, random
import yfinance as yf
import anthropic
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── フォント（GitHub Actions ubuntu-latest 上でインストールする）──
FONT_B = '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'
FONT_R = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
W, H   = 1080, 1350
BG=(13,15,20); RED=(220,60,60); WHITE=(240,242,248)
GRAY=(125,130,145); DARK=(10,12,17)
HEADER_H=278; SECTION_H=58; ROW1_H=186; ROW2_H=144; ROW3_H=144
CHART_H=282;  BOTTOM_H=258
Y_SECTION=HEADER_H; Y_ROW1=Y_SECTION+SECTION_H
Y_ROW2=Y_ROW1+ROW1_H; Y_ROW3=Y_ROW2+ROW2_H
Y_CHART=Y_ROW3+ROW3_H; Y_BOTTOM=Y_CHART+CHART_H

NIKKEI225_TICKERS = {
    '7203.T':'トヨタ自動車','6758.T':'ソニーグループ','9984.T':'ソフトバンクG',
    '8306.T':'三菱UFJ FG','6501.T':'日立製作所','6861.T':'キーエンス',
    '4063.T':'信越化学工業','8035.T':'東京エレクトロン','7974.T':'任天堂',
    '6367.T':'ダイキン工業','4519.T':'中外製薬','9432.T':'NTT',
    '9433.T':'KDDI','9434.T':'ソフトバンク','7267.T':'ホンダ',
    '7269.T':'スズキ','7751.T':'キヤノン','6702.T':'富士通',
    '4661.T':'オリエンタルランド','2802.T':'味の素','2914.T':'JT',
    '3382.T':'セブン&アイHD','8801.T':'三井不動産','8802.T':'三菱地所',
    '9020.T':'JR東日本','5401.T':'日本製鉄','4503.T':'アステラス製薬',
    '4568.T':'第一三共','6971.T':'京セラ','8316.T':'三井住友FG',
    '8411.T':'みずほFG','7832.T':'バンダイナムコ','6098.T':'リクルートHD',
    '6954.T':'ファナック','7011.T':'三菱重工業','6301.T':'小松製作所',
    '6326.T':'クボタ','5802.T':'住友電工','3407.T':'旭化成','4452.T':'花王',
    '5108.T':'ブリヂストン','7013.T':'IHI','4689.T':'LY Corporation','9022.T':'JR東海',
}

def _font(p, s):
    try: return ImageFont.truetype(p, s)
    except: return ImageFont.load_default()

def _cx(draw, text, y, f, color, gap=10, max_w=W-80):
    lines = []
    for raw in text.split('\n'):
        if not raw: lines.append(''); continue
        line = ''
        for ch in raw:
            if draw.textlength(line+ch, font=f) > max_w and line: lines.append(line); line = ch
            else: line += ch
        lines.append(line)
    for ln in lines:
        bx = draw.textbbox((0,0), ln, font=f); lw = bx[2]-bx[0]
        draw.text(((W-lw)//2, y), ln, font=f, fill=color); y += bx[3]-bx[1]+gap
    return y

def _calc_rsi(closes, n=14):
    if len(closes) < n+1: return [50.0]*len(closes)
    rv=[50.0]*n; g=[]; l=[]
    for i in range(1, len(closes)):
        d=closes[i]-closes[i-1]; g.append(max(d,0)); l.append(max(-d,0))
    for i in range(n, len(closes)):
        ag=sum(g[i-n:i])/n; al=sum(l[i-n:i])/n
        rv.append(round(100-(100/(1+ag/al)) if al else 100.0, 1))
    return rv

# ── STEP1: データ取得 ─────────────────────────────────

def get_fear_greed():
    try:
        hist = yf.Ticker('^VIX').history(period='5d')
        if hist.empty: return 50.0
        vix = hist['Close'].tolist(); v = vix[-1]
        level  = max(0.0, min(100.0, 100-(v-12)*(100/(35-12))))
        chg    = (vix[-1]-vix[-2])/vix[-2]*100 if len(vix)>=2 else 0
        change = max(0.0, min(100.0, 50-chg*2))
        return round(level*0.7+change*0.3, 1)
    except: return 50.0

def fetch_universe(tickers_dict, max_workers=8):
    def _one(item):
        ticker, name = item
        try:
            t = yf.Ticker(ticker); hist = t.history(period='60d')
            if hist.empty or len(hist) < 15: return None
            closes = [round(v,1) for v in hist['Close'].tolist()]
            dates  = [d.date() if hasattr(d,'date') else d for d in hist.index.tolist()]
            rsi_s  = _calc_rsi(closes)
            pc     = round((closes[-1]-closes[-2])/closes[-2]*100, 2)
            mc_en  = getattr(t.fast_info,'market_cap',None)
            return dict(ticker=ticker, name=name, closes=closes, dates=dates,
                        rsi_series=rsi_s, price_change=pc, rsi=rsi_s[-1],
                        market_cap=round(mc_en/1e8) if mc_en else 0)
        except: return None
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for f in as_completed({ex.submit(_one,i):i for i in tickers_dict.items()}):
            r = f.result()
            if r: results.append(r)
    return results

# ── STEP2: スクリーニング＋ランキング ────────────────

def rank_stocks(stocks, fear_greed,
                rsi_threshold=45, price_threshold=-3,
                mcap_min=5000, top_n=3):
    filtered = [s for s in stocks
                if s['rsi'] < rsi_threshold
                and s['price_change'] <= price_threshold
                and s['market_cap'] >= mcap_min]
    if not filtered:
        print('条件に合致なし → RSI最低順で表示')
        filtered = sorted(stocks, key=lambda s: s['rsi'])[:top_n]
    for s in filtered:
        rs = max(0, min(100, (45-s['rsi'])/45*100))
        ps = max(0, min(100, abs(s['price_change'])/20*100))
        s['score'] = round(rs*0.6+ps*0.4)
    ranked = sorted(filtered, key=lambda s: s['score'], reverse=True)[:top_n]
    for i, s in enumerate(ranked, 1):
        print(f'{i}位 {s["name"]}  RSI{s["rsi"]}  {s["price_change"]:+.1f}%  スコア{s["score"]}')
    return ranked

# ── STEP3: Claude APIで概況生成 ──────────────────────

SYSTEM_PROMPT = ('あなたは日本株市場のデータを教育目的で解説するコンテンツ作成者です。\n'
    '【禁止】売買推奨・将来予測の断定\n'
    '【出力】以下JSONのみ。\n'
    '{"summary":"概況（60文字以内）","hashtags":["タグ1","タグ2","タグ3","タグ4"]}')

def generate_script(ranked, fear_greed):
    client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])
    stocks_text = '\n'.join(
        f'{i+1}位: {s["name"]}（RSI {s["rsi"]}、前日比 {s["price_change"]:+.1f}%、スコア {s["score"]}）'
        for i,s in enumerate(ranked))
    resp = client.messages.create(
        model='claude-sonnet-4-6', max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{'role':'user','content':f'市場心理スコア: {fear_greed}\n\n{stocks_text}\n\nJSONのみ出力'}])
    raw = ''.join(b.text for b in resp.content if b.type=='text').strip()
    return json.loads(raw.replace('```json','').replace('```','').strip())

# ── STEP4: 画像生成 ──────────────────────────────────

def make_small_chart(dates, closes, rsi_values, width=988, height=234, dpi=150):
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(width/dpi, height/dpi), dpi=dpi,
        gridspec_kw={'height_ratios':[2,1]}, sharex=True)
    fig.patch.set_facecolor('#0D0F14')
    for ax in (a1, a2):
        ax.set_facecolor('#13161F'); ax.tick_params(colors='#808590', labelsize=8)
        for sp in ax.spines.values(): sp.set_color('#2A2D3A'); sp.set_alpha(0.6)
        ax.grid(True, color='#2A2D3A', alpha=0.5, lw=0.4)
    n = min(6, len(closes))
    if n < len(closes): a1.plot(dates[:-n], closes[:-n], color='#7A8099', lw=1.6, alpha=0.8)
    a1.plot(dates[-n:], closes[-n:], color='#DC3C3C', lw=2.2)
    a1.scatter([dates[-1]], [closes[-1]], color='#DC3C3C', s=32, zorder=5)
    a1.annotate(f'{closes[-1]:,.0f}', (dates[-1], closes[-1]),
        xytext=(6,4), textcoords='offset points', color='#DC3C3C', fontsize=9, fontweight='bold')
    a1.set_ylabel('Price', color='#808590', fontsize=8)
    a2.plot(dates, rsi_values, color='#5BA8E8', lw=1.6)
    a2.axhline(35, color='#DC3C3C', lw=0.8, ls='--', alpha=0.6)
    a2.axhline(70, color='#3CAA64', lw=0.8, ls='--', alpha=0.4)
    a2.fill_between(dates, 0, 35, color='#DC3C3C', alpha=0.07)
    a2.set_ylim(0, 100); a2.set_ylabel('RSI', color='#808590', fontsize=8)
    a2.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
    fig.autofmt_xdate(rotation=0, ha='center'); plt.tight_layout(pad=0.8)
    buf = io.BytesIO(); fig.savefig(buf, format='png', facecolor='#0D0F14')
    plt.close(fig); buf.seek(0)
    return Image.open(buf).convert('RGBA')

def draw_row(draw, img, rank, stock, y, row_h, is_first=False):
    badge_cols=[(RED,WHITE),((55,60,80),(175,180,198)),((35,38,52),(105,110,128))]
    score_cols=[RED,(145,150,168),(88,92,108)]; bar_fills=[RED,(62,67,85),(40,44,60)]
    bc,btxt=badge_cols[rank-1]; sc=score_cols[rank-1]; bf=bar_fills[rank-1]
    if is_first:
        draw.rectangle([(0,y),(W,y+row_h)], fill=(19,15,15))
        draw.rectangle([(0,y),(4,y+row_h)], fill=RED)
    else: draw.rectangle([(0,y),(W,y+row_h)], fill=((17,20,28) if rank==2 else (15,17,25)))
    draw.line([(40,y),(W-40,y)], fill=(32,36,52), width=1)
    name_sz=50 if is_first else 40; meta_sz=30 if is_first else 26
    score_sz=66 if is_first else 54; badge_sz=40 if is_first else 34; BR=36 if is_first else 30
    name_f=_font(FONT_B,name_sz); meta_f=_font(FONT_R,meta_sz)
    score_f=_font(FONT_B,score_sz); badge_f=_font(FONT_B,badge_sz)
    slabel_f=_font(FONT_R,22); label_f=_font(FONT_R,meta_sz-6)
    BX=48+BR; BY=y+row_h//2
    draw.ellipse([(BX-BR,BY-BR),(BX+BR,BY+BR)], fill=bc)
    rt=str(rank); rb=draw.textbbox((0,0),rt,font=badge_f)
    draw.text((BX-(rb[0]+rb[2])//2, BY-(rb[1]+rb[3])//2), rt, font=badge_f, fill=btxt)
    TX=BX+BR+24
    draw.text((TX,y+16), stock['name'], font=name_f, fill=WHITE)
    name_bot = y+16+draw.textbbox((0,0),stock['name'],font=name_f)[3]
    meta_y = name_bot+10
    pc=stock['price_change']; pc_str=f'{pc:+.1f}%'; rsi_str=f'{stock["rsi"]:.1f}'
    ticker=stock['ticker'].replace('.T',''); pc_clr=(210,55,55) if pc<0 else (55,190,100)
    cx=TX
    draw.text((cx,meta_y),ticker,font=meta_f,fill=GRAY); cx+=draw.textbbox((0,0),ticker,font=meta_f)[2]+16
    draw.text((cx,meta_y),'｜',font=meta_f,fill=(50,55,70)); cx+=draw.textbbox((0,0),'｜',font=meta_f)[2]+10
    draw.text((cx,meta_y+4),'前日比',font=label_f,fill=GRAY); cx+=draw.textbbox((0,0),'前日比',font=label_f)[2]+8
    draw.text((cx,meta_y),pc_str,font=meta_f,fill=pc_clr); cx+=draw.textbbox((0,0),pc_str,font=meta_f)[2]+16
    draw.text((cx,meta_y),'｜',font=meta_f,fill=(50,55,70)); cx+=draw.textbbox((0,0),'｜',font=meta_f)[2]+10
    draw.text((cx,meta_y+4),'RSI',font=label_f,fill=GRAY); cx+=draw.textbbox((0,0),'RSI',font=label_f)[2]+8
    draw.text((cx,meta_y),rsi_str,font=meta_f,fill=WHITE)
    SCORE_X=W-175; BAR_Y=y+row_h-18
    sb=draw.textbbox((0,0),str(stock['score']),font=score_f); sw_=sb[2]-sb[0]
    slbl_bb=draw.textbbox((0,0),'SCORE',font=slabel_f); slbl_h=slbl_bb[3]-slbl_bb[1]
    total_h=sb[3]+8+slbl_h; center_y=y+(BAR_Y-y)//2; block_top=center_y-total_h//2
    draw.text((SCORE_X+(140-sw_)//2,block_top),str(stock['score']),font=score_f,fill=sc)
    slbl_x=SCORE_X+(140-(slbl_bb[2]-slbl_bb[0]))//2
    draw.text((slbl_x,block_top+sb[3]+8),'SCORE',font=slabel_f,fill=GRAY)
    PAD=44; BW=W-PAD*2
    draw.rectangle([(PAD,BAR_Y),(PAD+BW,BAR_Y+10)], fill=(26,29,42))
    filled=int(BW*stock['score']/100)
    if filled>0: draw.rectangle([(PAD,BAR_Y),(PAD+filled,BAR_Y+10)], fill=bf)

def build_image(ranked, fear_greed, script):
    img=Image.new('RGB',(W,H),BG); d=ImageDraw.Draw(img)
    d.rectangle([(0,0),(W,HEADER_H)], fill=(16,8,8))
    label_f=_font(FONT_R,33); label_txt='市場恐怖度（独自算出）'
    label_bb=d.textbbox((0,0),label_txt,font=label_f); label_y=40  # 上余白確保
    d.text(((W-(label_bb[2]-label_bb[0]))//2,label_y),label_txt,font=label_f,fill=GRAY)
    label_bot=label_y+label_bb[3]
    num_f=_font(FONT_B,108); num_s=str(int(fear_greed))  # 120→108 ヘッダー内に収める
    num_bb=d.textbbox((0,0),num_s,font=num_f); num_y=label_bot+8
    d.text(((W-(num_bb[2]-num_bb[0]))//2,num_y),num_s,font=num_f,fill=RED)
    num_bot=num_y+num_bb[3]
    date_f=_font(FONT_R,27); date_str=datetime.date.today().strftime('%Y.%m.%d')
    date_bb=d.textbbox((0,0),date_str,font=date_f); date_y=num_bot+8
    d.text(((W-(date_bb[2]-date_bb[0]))//2,date_y),date_str,font=date_f,fill=(55,60,78))
    d.rectangle([(0,Y_SECTION),(W,Y_SECTION+SECTION_H)], fill=(18,20,28))
    _cx(d,'売られすぎランキング  TOP3',Y_SECTION+10,_font(FONT_B,36),(208,213,228))
    draw_row(d,img,1,ranked[0],Y_ROW1,ROW1_H,is_first=True)
    if len(ranked)>1: draw_row(d,img,2,ranked[1],Y_ROW2,ROW2_H)
    if len(ranked)>2: draw_row(d,img,3,ranked[2],Y_ROW3,ROW3_H)
    d.rectangle([(0,Y_CHART),(W,Y_CHART+CHART_H)], fill=(11,13,18))
    d.text((44,Y_CHART+10),f'1位 {ranked[0]["name"]} チャート（30日）',font=_font(FONT_B,26),fill=GRAY)
    chart=make_small_chart(ranked[0]['dates'],ranked[0]['closes'],ranked[0]['rsi_series'],width=988,height=228,dpi=150)
    img.paste(chart.resize((988,234),Image.LANCZOS).convert('RGB'),((W-988)//2,Y_CHART+42))
    d.rectangle([(0,Y_BOTTOM),(W,H)], fill=DARK)
    d.line([(40,Y_BOTTOM+2),(W-40,Y_BOTTOM+2)], fill=(30,34,50), width=1)
    next_y=_cx(d,script['summary'],Y_BOTTOM+22,_font(FONT_R,34),(198,203,218),gap=12)
    next_y=_cx(d,'  '.join(f'#{h}' for h in script['hashtags']),next_y+8,_font(FONT_R,29),(72,120,190))
    _cx(d,'本コンテンツは教育目的の情報提供です。投資助言ではありません。',next_y+12,_font(FONT_R,23),(56,60,76))
    return img


# ── メイン ───────────────────────────────────────────

if __name__ == '__main__':
    print('=== 市場恐怖度ランキング 画像生成開始 ===')
    print(f'実行日時: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')

    print('\n[STEP1] データ取得中...')
    fear_greed = get_fear_greed()
    print(f'  市場心理スコア: {fear_greed}')
    stocks = fetch_universe(NIKKEI225_TICKERS, max_workers=8)
    print(f'  取得完了: {len(stocks)}/{len(NIKKEI225_TICKERS)} 銘柄')

    print('\n[STEP2] スクリーニング...')
    ranked = rank_stocks(stocks, fear_greed)

    print('\n[STEP3] Claude API で概況生成...')
    script = generate_script(ranked, fear_greed)
    print(f'  概況: {script["summary"]}')

    print('\n[STEP4] 画像生成...')
    img = build_image(ranked, fear_greed, script)
    today = datetime.date.today().strftime('%Y-%m-%d')
    out_path = Path(f'ranking_{today}.jpg')
    img.save(out_path, 'JPEG', quality=95)
    print(f'  保存: {out_path}  ({img.size[0]}x{img.size[1]}px)')

    print(f'\n完了！ {out_path} をダウンロードしてInstagramに投稿してください。')

    print('\n=== 完了 ===')
