# alert-weather

필요할 때만 오는 날씨 알림. 홈랩 claude LXC의 cron이 매일 07:00 KST에 돌고,
비/눈, 미세먼지 나쁨, 한파·급추위, 폭염, 강풍일 때만 Slack `#alert-weather`로 보낸다.
맑은 날은 아무것도 안 온다.

- `alert_weather.py`: 판단 + Slack 전송 (Python 표준 라이브러리만 사용, 데이터는 Open-Meteo)
- `index.html`: 메시지의 "복사해서 보내기" 버튼이 여는 페이지 (GitHub Pages). 문구는 URL `#` 뒤에만 실려서 서버로 전송되지 않는다.

## 판단 기준 (07~22시)

| 항목 | 기준 |
|-|-|
| 비/눈 | 강수확률 70% 이상, 또는 50% 이상이면서 강수량 0.1mm 이상인 시간이 있음 |
| 미세먼지 | 낮 평균 PM10 81 이상 또는 PM2.5 36 이상 (환경부 나쁨 기준) |
| 추위 | 최저 -5도 이하, 체감 -10도 이하, 또는 어제 최저보다 6도 이상 하락 |
| 폭염 | 최고 33도 이상 |
| 강풍 | 순간풍속 15m/s 이상 |

## 설치

```sh
mkdir -p ~/alert-weather ~/.config/weather-alert
curl -fsSL https://raw.githubusercontent.com/mydreamishapping/alert-weather/main/alert_weather.py -o ~/alert-weather/alert_weather.py
printf 'LAT=37.5615\nLON=126.8545\nPLACE=강서구 가양동\nSHARE_URL=https://mydreamishapping.github.io/alert-weather/\n' > ~/.config/weather-alert/env
# 웹훅 URL은 ~/.config/weather-alert/slack_webhook 에 저장 (chmod 600)
( crontab -l; echo 'CRON_TZ=Asia/Seoul'; echo '0 7 * * * /usr/bin/python3 $HOME/alert-weather/alert_weather.py >> $HOME/alert-weather/run.log 2>&1' ) | crontab -
```
