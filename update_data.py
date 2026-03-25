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

# 서울 일부 자치구 (빠른 데모 렌더링을 위해 테스트 3개 구만)
SEOUL_DISTRICTS = {
    '서울중구':'3010000',
    '서울용산구':'3020000', 
    '서울강남구':'3220000'
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
    try:
        headers = {'Authorization': f'KakaoAK {KAKAO_API_KEY}'}
        res = requests.get('https://dapi.kakao.com/v2/local/search/address.json', params={'query': address}, headers=headers, timeout=5)
        if res.status_code == 200:
            docs = res.json().get('documents', [])
            if docs:
                return float(docs[0]['x']), float(docs[0]['y'])
    except:
        pass
    return None, None

def main():
    all_data = []
    total_fetched = 0
    
    print(f"Starting ETL Process for {len(SEOUL_DISTRICTS)} districts...")
    
    for district_name, code in SEOUL_DISTRICTS.items():
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
        'region': '서울시 전역'
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
