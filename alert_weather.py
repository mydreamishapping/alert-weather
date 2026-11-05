#!/usr/bin/env python3
"""alert-weather: 필요할 때만 오는 날씨 알림 (Slack incoming webhook)

비/눈, 미세먼지 나쁨, 한파/급추위, 폭염, 강풍일 때만 메시지를 보낸다.
해당 사항이 없으면 아무것도 보내지 않는다.

설정: ~/.config/weather-alert/env  (웹훅은 ~/.config/weather-alert/slack_webhook, chmod 600)
  LAT=37.5615
  LON=126.8545
  PLACE=강서구 가양동
  SHARE_URL=https://mydreamishapping.github.io/alert-weather/
  GF_PREFIX=            (선택, 예: "자기야 ")

사용법:
  alert_weather.py              오늘 기준, 조건 맞을 때만 전송
  alert_weather.py --tomorrow   내일 기준
  alert_weather.py --dry        전송 없이 출력만
  alert_weather.py --force      조건 없어도 전송 (테스트)
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request

KST = dt.timezone(dt.timedelta(hours=9))
CONF = os.path.expanduser("~/.config/weather-alert/env")
HOOK = os.path.expanduser("~/.config/weather-alert/slack_webhook")
DAY_START, DAY_END = 7, 22  # 활동 시간대 (시)

# 기준값
RAIN_PROB_SURE = 70      # 이 이상이면 강수량과 상관없이 비 시간으로 봄
RAIN_PROB_MIN = 50       # 이 이상 + 강수량 0.1mm 이상이면 비 시간
PM10_BAD, PM10_VBAD = 81, 151
PM25_BAD, PM25_VBAD = 36, 76
COLD_MIN = -5            # 최저기온
FEELS_COLD = -10         # 체감온도
DROP = 6                 # 어제 최저 대비 하락폭
HOT_MAX = 33
GUST_KMH = 54            # 약 15m/s


def load_conf():
    conf = {}
    if os.path.exists(CONF):
        for line in open(CONF, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                conf[k.strip()] = v.strip().strip('"')
    if os.path.exists(HOOK):
        conf["WEBHOOK_URL"] = open(HOOK, encoding="utf-8").read().strip()
    return conf


def get_json(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                return json.load(r)
        except Exception as e:  # noqa
            if i == tries - 1:
                raise
            time.sleep(5 * (i + 1))


def r0(x):
    """반올림 정수 (-0 방지)"""
    return int(round(x)) + 0


def hour_ranges(hours):
    """[7,8,9,15,16] -> '07~09시, 15~16시'"""
    if not hours:
        return ""
    out, start, prev = [], hours[0], hours[0]
    for h in hours[1:] + [None]:
        if h is not None and h == prev + 1:
            prev = h
            continue
        out.append(f"{start:02d}시" if start == prev else f"{start:02d}~{prev:02d}시")
        if h is not None:
            start = prev = h
    return ", ".join(out)


def when_word(h):
    if h < 12:
        return "오전"
    if h < 18:
        return "오후"
    return "저녁"


def analyze(conf, target):
    lat, lon = conf.get("LAT", "37.5615"), conf.get("LON", "126.8545")
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "timezone": "Asia/Seoul",
        "hourly": "temperature_2m,apparent_temperature,precipitation_probability,"
                  "precipitation,snowfall,wind_gusts_10m",
        "daily": "temperature_2m_max,temperature_2m_min",
        "past_days": 1, "forecast_days": 3,
    })
    w = get_json("https://api.open-meteo.com/v1/forecast?" + q)
    q2 = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "timezone": "Asia/Seoul",
        "hourly": "pm10,pm2_5", "past_days": 1, "forecast_days": 3,
    })
    try:
        aq = get_json("https://air-quality-api.open-meteo.com/v1/air-quality?" + q2)
    except Exception:
        aq = None

    day = target.isoformat()
    prev_day = (target - dt.timedelta(days=1)).isoformat()
    H = w["hourly"]
    idx = [i for i, t in enumerate(H["time"])
           if t.startswith(day) and DAY_START <= int(t[11:13]) <= DAY_END]
    if not idx:
        raise RuntimeError("no forecast hours for " + day)

    def col(name):
        return [(int(H["time"][i][11:13]), H[name][i]) for i in idx if H[name][i] is not None]

    D = w["daily"]
    dmax = D["temperature_2m_max"][D["time"].index(day)]
    dmin = D["temperature_2m_min"][D["time"].index(day)]
    ymin = D["temperature_2m_min"][D["time"].index(prev_day)] if prev_day in D["time"] else None

    items = []      # (headline, detail)
    gf = []         # 여친한테 보낼 문장 조각

    # 비 / 눈
    prob = dict(col("precipitation_probability"))
    rain = dict(col("precipitation"))
    snow = dict(col("snowfall"))
    wet = sorted(h for h in prob if prob[h] >= RAIN_PROB_SURE
                 or (prob[h] >= RAIN_PROB_MIN and rain.get(h, 0) >= 0.1))
    snow_cm = sum(v for v in snow.values() if v)
    if wet:
        pmax = max(prob[h] for h in wet)
        mm = sum(rain.get(h, 0) or 0 for h in wet)
        kind = "눈" if snow_cm >= 0.5 else "비"
        detail = f"{hour_ranges(wet)} · 강수확률 최대 {pmax}%"
        if mm >= 1:
            detail += f" · 약 {mm:.0f}mm"
        if kind == "눈":
            detail += f" · 적설 약 {snow_cm:.1f}cm"
        items.append((f"{kind} 와요, 우산 챙기세요", detail))
        first = wet[0]
        if first <= DAY_START + 1:
            gf.append(f"오늘 아침부터 {kind} 온대. 우산 꼭 챙겨!")
        else:
            gf.append(f"오늘 {when_word(first)} {first if first <= 12 else first - 12}시쯤부터 {kind} 온대. 우산 꼭 챙겨!")
        if kind == "눈":
            gf.append("길 미끄러우니까 조심하고.")

    # 미세먼지
    if aq:
        A = aq["hourly"]
        aidx = [i for i, t in enumerate(A["time"])
                if t.startswith(day) and DAY_START <= int(t[11:13]) <= DAY_END]
        pm10 = [A["pm10"][i] for i in aidx if A["pm10"][i] is not None]
        pm25 = [A["pm2_5"][i] for i in aidx if A["pm2_5"][i] is not None]
        if pm10 and pm25:
            a10, a25 = sum(pm10) / len(pm10), sum(pm25) / len(pm25)
            grade = None
            if a10 >= PM10_VBAD or a25 >= PM25_VBAD:
                grade = "매우 나쁨"
            elif a10 >= PM10_BAD or a25 >= PM25_BAD:
                grade = "나쁨"
            if grade:
                items.append((f"미세먼지 {grade}, 마스크 챙기세요",
                              f"낮 평균 미세먼지 {a10:.0f} · 초미세먼지 {a25:.0f} ㎍/㎥"))
                gf.append(f"미세먼지 {grade}이래. 마스크 쓰고 다녀.")

    # 한파 / 급추위
    feels = col("apparent_temperature")
    fmin = min(v for _, v in feels) if feels else None
    cold = dmin <= COLD_MIN or (fmin is not None and fmin <= FEELS_COLD)
    drop = ymin is not None and (ymin - dmin) >= DROP
    if cold or drop:
        bits = [f"최저 {r0(dmin)}도 / 최고 {r0(dmax)}도"]
        if fmin is not None:
            bits.append(f"체감 최저 {r0(fmin)}도")
        if drop:
            bits.append(f"어제보다 {r0(ymin - dmin)}도 낮음")
        if cold:
            items.append(("많이 추워요, 따뜻하게 입으세요", " · ".join(bits)))
            gf.append(f"오늘 최저 {r0(dmin)}도래. 진짜 추우니까 따뜻하게 입고 나가!")
        else:
            items.append(("어제보다 확 추워져요, 겉옷 챙기세요", " · ".join(bits)))
            gf.append(f"오늘 어제보다 {r0(ymin - dmin)}도나 떨어진대. 겉옷 하나 더 챙겨!")

    # 폭염
    if dmax >= HOT_MAX:
        items.append(("폭염이에요, 물 챙기세요", f"최고 {r0(dmax)}도"))
        gf.append(f"오늘 최고 {r0(dmax)}도래. 너무 더우니까 물 많이 마셔.")

    # 강풍
    gust = col("wind_gusts_10m")
    if gust:
        gh, gv = max(gust, key=lambda x: x[1])
        if gv >= GUST_KMH:
            items.append(("바람 강해요", f"{gh:02d}시쯤 순간풍속 약 {gv / 3.6:.0f}m/s"))
            gf.append("바람도 엄청 세대. 조심해.")

    summary = f"최저 {r0(dmin)}도 / 최고 {r0(dmax)}도"
    return items, gf, summary


def build_message(conf, target, items, gf, summary):
    place = conf.get("PLACE", "강서구 가양동")
    wd = "월화수목금토일"[target.weekday()]
    datestr = f"{target.month}/{target.day}({wd})"
    if items:
        headline = items[0][0] if len(items) == 1 else " + ".join(h.split(",")[0] for h, _ in items)
    else:
        headline = "특별히 챙길 건 없어요"
    gf_text = (conf.get("GF_PREFIX", "") + " ".join(gf)).strip() or "오늘 날씨 괜찮대. 좋은 하루 보내!"
    share = conf.get("SHARE_URL", "").rstrip("/") + "/#" + urllib.parse.quote(gf_text)

    if len(items) == 1:
        lines = items[0][1]
    else:
        lines = "\n".join(f"• *{h}*\n    {d}" for h, d in items) or summary
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"{datestr} {headline}"[:150]}},
        {"type": "section", "text": {"type": "mrkdwn", "text": lines}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*여친한테 보낼 말*\n>" + gf_text}},
    ]
    if conf.get("SHARE_URL"):
        blocks.append({"type": "actions", "elements": [{
            "type": "button", "style": "primary", "action_id": "copy_gf",
            "text": {"type": "plain_text", "text": "복사해서 보내기"},
            "url": share[:3000],
        }]})
    blocks.append({"type": "context", "elements": [{
        "type": "mrkdwn", "text": f"{place} · {summary} · Open-Meteo · claude LXC cron"}]})
    return {"text": f"{datestr} {headline}", "blocks": blocks}


def main():
    args = set(sys.argv[1:])
    conf = load_conf()
    today = dt.datetime.now(KST).date()
    target = today + dt.timedelta(days=1) if "--tomorrow" in args else today
    items, gf, summary = analyze(conf, target)
    stamp = dt.datetime.now(KST).strftime("%F %T")
    if not items and "--force" not in args:
        print(f"{stamp} {target} 조건 없음, 전송 안 함 ({summary})")
        return
    msg = build_message(conf, target, items, gf, summary)
    if "--dry" in args or not conf.get("WEBHOOK_URL"):
        print(json.dumps(msg, ensure_ascii=False, indent=1))
        return
    req = urllib.request.Request(conf["WEBHOOK_URL"], data=json.dumps(msg).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        print(f"{stamp} {target} 전송 {r.status}: {msg['text']}")


if __name__ == "__main__":
    main()
