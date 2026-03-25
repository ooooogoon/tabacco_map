import requests
import json
import time
from datetime import datetime
import pyproj
import os

API_KEY = 'e73f0e74186728df4cc7a0b30825e3b65e04519363781be92faa5511083d30d8'
URL = 'https://apis.data.go.kr/1741000/tobacco_retailers/info'
KAKAO_API_KEY = '21792ed90da16b4da6ab0d8978b26cd1' # JS key (might not work with REST, but let's try fallback)

# 중부원점(TM) -> WGS84 변환기 (proj4: EPSG:5174)
tm_proj = pyproj.Proj('+proj=tmerc +lat_0=38 +lon_0=127 +k=1 +x_0=200000 +y_0=500000 +ellps=bessel +towgs84=-146.43,507.89,681.46,0,0,0,0 +units=m +no_defs')
wgs84_proj = pyproj.Proj('epsg:4326')
transformer = pyproj.Transformer.from_proj(tm_proj, wgs84_proj, always_xy=True)

# 서울, 경기, 인천 자치구
TARGET_DISTRICTS = {
    '서울종로구':'3000000', '서울중구':'3010000', '서울용산구':'3020000', '서울성동구':'3030000',
    '서울광진구':'3040000', '서울동대문구':'3050000', '서울중랑구':'3060000', '서울성북구':'3070000',
    '서울강북구':'3080000', '서울도봉구':'3090000', '서울노원구':'3100000', '서울은평구':'3110000',
    '서울서대문구':'3120000', '서울마포구':'3130000', '서울양천구':'3140000', '서울강서구':'3150000',
    '서울구로구':'3160000', '서울금천구':'3170000', '서울영등포구':'3180000', '서울동작구':'3190000',
    '서울관악구':'3200000', '서울서초구':'3210000', '서울강남구':'3220000', '서울송파구':'3230000',
    '서울강동구':'3240000',
    '인천중구':'3490000', '인천동구':'3500000', '인천미추홀구':'3510500', '인천연수구':'3520000',
    '인천남동구':'3530000', '인천부평구':'3540000', '인천계양구':'3550000', '인천서구':'3560000',
    '인천강화군':'3570000', '인천옹진군':'3580000',
    '경기수원시':'3740000', '경기성남시':'3780000', '경기의정부시':'3820000', '경기안양시':'3830000',
    '경기부천시':'3860000', '경기광명시':'3900000', '경기평택시':'3910000', '경기동두천시':'3920000',
    '경기안산시':'3930000', '경기고양시':'3940000', '경기과천시':'3970000', '경기구리시':'3980000',
    '경기남양주시':'3990000', '경기오산시':'4000000', '경기시흥시':'4010000', '경기군포시':'4020000',
    '경기의왕시':'4030000', '경기하남시':'4040000', '경기용인시':'4050000', '경기파주시':'4060000',
    '경기이천시':'4070000', '경기안성시':'4080000', '경기김포시':'4090000', '경기양평군':'4170000',
    '경기연천군':'4140000', '경기가평군':'4160000', '경기광주시':'5540000', '경기화성시':'5530000',
    '경기양주시':'5590000', '경기포천시':'5600000', '경기여주시':'5700000'
}

def clean_business_name(name):
    if not name: return name
    s = name
    for p in ['주식회사 ', '유한회사 ', '(주)', '㈜', '(유)']:
        s = s.replace(p, '')
    s = s.replace('코리아세븐', '세븐일레븐 ')
    s = s.replace('BGF리테일', 'CU ')
    s = s.replace('GS리테일 GS25', 'GS25 ')
    s = s.replace('GS리테일', 'GS25 ')
    s = s.replace('이마트에브리데이', '이마트24 ')
    return ' '.join(s.split()) or name

def geocode_kakao(address):
    # 속도 저하의 주원인으로, 카카오 지오코딩 폴백은 완전히 비활성화합니다.
    return None, None

def main():
    all_data = []
    total_fetched = 0
    
    print(f"Starting ETL Process for {len(TARGET_DISTRICTS)} districts...")
    
    for district_name, code in TARGET_DISTRICTS.items():
        page = 1
        loaded = 0
        total = 0
        print(f"[{district_name}] Fetching data...")
        
        while True:
            params = {
                'serviceKey': API_KEY,
                'pageNo': page,
                'numOfRows': 1000,
                'returnType': 'json',
                'cond[OPN_ATMY_GRP_CD::EQ]': code
            }
            try:
                # 공공데이터 포털은 가끔 연결이 끊기므로 재시도 로직 추가
                res = requests.get(URL, params=params, verify=False, timeout=15)
                data = res.json()
            except Exception as e:
                print(f"Error fetching page {page}: {e}")
                time.sleep(2)
                continue
                
            body = data.get('response', {}).get('body', {})
            if page == 1:
                total = int(body.get('totalCount', 0))
                if total == 0:
                    break
                    
            items = body.get('items', {}).get('item', [])
            if isinstance(items, dict): items = [items]
            if not items: break
            
            for item in items:
                bplcNm = clean_business_name(item.get('BPLC_NM', '알수없음'))
                dtl = item.get('DTL_SALS_STTS_NM', item.get('SALS_STTS_NM', ''))
                addr = item.get('ROAD_NM_ADDR') or item.get('LOTNO_ADDR') or ''
                apvDt = item.get('LCPMT_YMD', '')
                clgDt = item.get('CLSBIZ_YMD', '')
                
                # 날짜 포맷
                if apvDt and len(apvDt) == 8: apvDt = f"{apvDt[:4]}-{apvDt[4:6]}-{apvDt[6:]}"
                if clgDt and len(clgDt) == 8: clgDt = f"{clgDt[:4]}-{clgDt[4:6]}-{clgDt[6:]}"
                
                lng, lat = None, None
                x = item.get('CRD_INFO_X')
                y = item.get('CRD_INFO_Y')
                
                if x and y and float(x) > 0 and float(y) > 0:
                    try:
                        # TM to WGS84
                        plng, plat = transformer.transform(float(x), float(y))
                        lng, lat = plng, plat
                    except Exception:
                        pass
                
                # TM 좌표가 이상하거나 누락된 경우 Kakao API 서브 호출 (너무 느리므로 50건 이내로만)
                if not lng and addr:
                    lng, lat = geocode_kakao(addr)
                    
                if lng and lat:
                    all_data.append({
                        'n': bplcNm,   # 용량 압축을 위해 키를 짧게
                        's': dtl,
                        'a': addr,
                        'o': apvDt,
                        'c': clgDt,
                        'x': round(lng, 6),
                        'y': round(lat, 6)
                    })
                    
            loaded += len(items)
            print(f"  -> Progress: {loaded}/{total}")
            if loaded >= total: break
            page += 1
            time.sleep(0.1) # Rate limit 방지

    now = datetime.now()
    fetch_date = now.strftime('%Y-%m-%d %H:%M')
    
    metadata = {
        'fetchDate': fetch_date,
        'apiUpdateDate': now.strftime('%Y-%m-%d'), # 보통 행안부 API는 전일 혹은 당일 새벽 기준
        'totalCount': len(all_data),
        'region': '수도권 (서울/경기/인천)'
    }
    
    # Save to data.json
    output_path = os.path.join(os.path.dirname(__file__), 'data.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump({'metadata': metadata, 'stores': all_data}, f, ensure_ascii=False, separators=(',', ':'))
        
    print(f"\nSuccessfully saved {len(all_data)} records to data.json")

if __name__ == '__main__':
    # SSL Warning 무시 (공공데이터 API)
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()
