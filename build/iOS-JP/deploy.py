#!/usr/bin/env python3
"""아스트랄 파티 iOS 한글패치 배포

=== 사전 요구사항 ===

1. Python 3.10+
   - macOS: brew install python3  또는  https://www.python.org
   - Windows: https://www.python.org (설치 시 "Add to PATH" 체크)

2. pymobiledevice3
   - pip install pymobiledevice3
   - Windows: Apple iTunes가 반드시 설치되어 있어야 함
     (Apple Mobile Device Service 드라이버 필요)
   - macOS: 추가 설치 없음

3. iOS 기기 연결
   - USB 케이블로 연결
   - 기기에서 "이 컴퓨터를 신뢰하겠습니까?" 팝업 → 신뢰 선택
   - macOS Sonoma+: 개인정보 보호 설정에서 USB 액세서리 허용 필요할 수 있음

4. 게임 앱 (com.feimo.astralpartyjp)
   - 앱이 기기에 설치되어 있어야 함
   - 최초 1회 이상 실행하여 리소스 다운로드 완료 상태여야 함
     (타이틀 화면까지 진입 → 리소스 다운로드 완료)
   - 배포 전 앱을 완전히 종료할 것 (백그라운드X, 강제종료 권장)

5. 배포 파일 구조 (이 스크립트와 같은 디렉토리)
   dist/
   ├── deploy.py          ← 이 스크립트
   ├── config.json         ← 번들 매핑 정보
   └── bundles/
       ├── font_main.bundle   (메인 폰트 - TTF + TMP + Atlas)
       ├── font_tmp.bundle    (TMP 폰트 - TMP + Atlas)
       ├── protobuf.bundle    (번역 텍스트)
       └── xml.bundle         (UI 텍스트)

=== 사용법 ===

  pip install pymobiledevice3
  python deploy.py

  배포 완료 후 앱을 재시작하면 한글패치 적용.
  게임 업데이트 시 리소스가 초기화되므로 재배포 필요.

=== 지원 환경 ===

  - macOS (arm64/x86_64) + iOS/iPadOS 26+
  - Windows 10/11 + iOS/iPadOS 26+ (iTunes 필수)
  - iPhone / iPad 모두 동일 스크립트로 배포
"""

import base64
import json
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'config.json')

ADDRESSABLES_DIR = 'Documents/com.unity.addressables'


def find_catalog(svc):
    """디바이스에서 catalog_*.json 파일 찾기"""
    try:
        entries = svc.listdir(ADDRESSABLES_DIR)
    except Exception:
        return None
    for name in entries:
        if name.startswith('catalog_') and name.endswith('.json'):
            return f'{ADDRESSABLES_DIR}/{name}'
    return None


def patch_catalog(catalog_bytes, bundle_hash, bundle_name, original_size, new_size):
    """카탈로그에서 font_main LOCAL→REMOTE 리다이렉트 + m_BundleSize 업데이트"""
    cat = json.loads(catalog_bytes)

    # 1. InternalId: RuntimePath → WebServerConfig.Path
    # InternalId에는 bundle_hash가 들어감 (e.g. 332c75ec....bundle)
    ids = cat['m_InternalIds']
    redirected = False
    for i, iid in enumerate(ids):
        if bundle_hash in iid and '{UnityEngine.AddressableAssets.Addressables.RuntimePath}' in iid:
            ids[i] = iid.replace(
                '{UnityEngine.AddressableAssets.Addressables.RuntimePath}',
                '{App.WebServerConfig.Path}',
            )
            redirected = True
            break

    if not redirected:
        for iid in ids:
            if bundle_hash in iid and '{App.WebServerConfig.Path}' in iid:
                redirected = True
                break

    if not redirected:
        print('  WARNING: font_main InternalId를 찾을 수 없음')
        return None

    # 2. ExtraData: m_BundleSize 업데이트
    extra_raw = base64.b64decode(cat['m_ExtraDataString'])

    # m_BundleName으로 해당 JSON entry 위치 찾기
    # ExtraData는 UTF-16LE. 각 entry는 {...} JSON 객체.
    # m_BundleName과 m_BundleSize가 같은 JSON 안에 있다.
    bundle_name_utf16 = bundle_name.encode('utf-16-le')
    name_pos = extra_raw.find(bundle_name_utf16)
    if name_pos < 0:
        print('  WARNING: ExtraData에서 bundle_name을 찾을 수 없음')
        return None

    # bundle_name 이후에서 가장 가까운 m_BundleSize 찾기 (같은 JSON 객체 내)
    size_key = '"m_BundleSize":'.encode('utf-16-le')
    size_pos = extra_raw.find(size_key, name_pos)
    if size_pos < 0 or size_pos - name_pos > 1024:
        print('  WARNING: ExtraData에서 m_BundleSize를 찾을 수 없음')
        return None

    # m_BundleSize 값 추출 및 교체
    val_start = size_pos + len(size_key)
    val_end = val_start
    while val_end < len(extra_raw):
        char = extra_raw[val_end:val_end + 2]
        if len(char) < 2:
            break
        ch = char.decode('utf-16-le', errors='replace')
        if ch.isdigit():
            val_end += 2
        else:
            break

    old_val = extra_raw[val_start:val_end].decode('utf-16-le')
    new_val_bytes = str(new_size).encode('utf-16-le')

    extra_patched = extra_raw[:val_start] + new_val_bytes + extra_raw[val_end:]

    cat['m_ExtraDataString'] = base64.b64encode(extra_patched).decode('ascii')

    print(f'  InternalId: LOCAL → REMOTE')
    print(f'  m_BundleSize: {old_val} → {new_size}')

    return json.dumps(cat, separators=(',', ':')).encode('utf-8')


def main():
    # config 로드
    if not os.path.exists(CONFIG_PATH):
        print('ERROR: config.json을 찾을 수 없습니다.')
        sys.exit(1)

    with open(CONFIG_PATH, 'r') as f:
        config = json.load(f)

    bundle_id = config['app_bundle_id']
    bundles = config['bundles']

    # 번들 파일 존재 확인
    missing = []
    for btype, info in bundles.items():
        path = os.path.join(SCRIPT_DIR, info['file'])
        if not os.path.exists(path):
            missing.append(info['file'])

    if missing:
        print('ERROR: 번들 파일 누락')
        for m in missing:
            print(f'  - {m}')
        sys.exit(1)

    # pymobiledevice3 import
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.house_arrest import HouseArrestService
    except ImportError:
        print('ERROR: pymobiledevice3가 설치되어 있지 않습니다.')
        print('  pip install pymobiledevice3')
        sys.exit(1)

    print('아스트랄 파티 iOS 한글패치')
    print('=' * 36)

    # 디바이스 연결
    print('디바이스 연결 확인 중...', end=' ', flush=True)
    try:
        lockdown = create_using_usbmux()
        print('OK')
    except Exception:
        print('FAIL')
        print('\nUSB로 iOS 기기를 연결하고 신뢰 설정을 확인하세요.')
        sys.exit(1)

    # 앱 접근
    try:
        svc = HouseArrestService(lockdown, bundle_id=bundle_id, documents_only=True)
    except Exception:
        print(f'\nERROR: {bundle_id} 앱에 접근할 수 없습니다.')
        print('앱이 설치되어 있는지 확인하세요.')
        sys.exit(1)

    print()

    LABELS = {
        'font_main': 'Font (main)',
        'font_tmp': 'Font (TMP)',
        'protobuf': 'Protobuf',
        'xml': 'XML',
    }

    # 카탈로그 패치 필요 여부 확인
    needs_catalog = any(
        info.get('needs_catalog_patch')
        for info in bundles.values()
    )

    success = True

    # 번들 배포
    for btype, info in bundles.items():
        label = LABELS.get(btype, btype)
        local_path = os.path.join(SCRIPT_DIR, info['file'])
        remote_path = info['device_path']

        with open(local_path, 'rb') as f:
            data = f.read()

        try:
            remote_dir = '/'.join(remote_path.split('/')[:-1])
            if not svc.exists(remote_dir):
                svc.makedirs(remote_dir)

            svc.set_file_contents(remote_path, data)
            verified = svc.stat(remote_path).get('st_size')
            status = 'OK' if verified == len(data) else f'SIZE MISMATCH ({verified})'
            print(f'{label + ":":<16} {len(data):>10,} bytes → {status}')

            # font_main: __info 메타데이터 생성
            if info.get('needs_catalog_patch'):
                info_path = remote_dir + '/__info'
                info_content = f'-1\n{int(time.time())}\n1\n__data\n'.encode()
                svc.set_file_contents(info_path, info_content)

        except Exception as e:
            print(f'{label + ":":<16} FAIL - {e}')
            success = False

    # 카탈로그 패치
    if needs_catalog and success:
        print()
        print('카탈로그 패치 중...')
        catalog_path = find_catalog(svc)
        if not catalog_path:
            print('  ERROR: 카탈로그 파일을 찾을 수 없음')
            success = False
        else:
            catalog_bytes = svc.get_file_contents(catalog_path)
            print(f'  카탈로그: {os.path.basename(catalog_path)} ({len(catalog_bytes):,} bytes)')

            for btype, info in bundles.items():
                if not info.get('needs_catalog_patch'):
                    continue

                bundle_path = os.path.join(SCRIPT_DIR, info['file'])
                new_size = os.path.getsize(bundle_path)

                patched = patch_catalog(
                    catalog_bytes,
                    info['bundle_hash'],
                    info['bundle_name'],
                    info['original_bundle_size'],
                    new_size,
                )
                if patched:
                    catalog_bytes = patched
                else:
                    success = False

            if success:
                svc.set_file_contents(catalog_path, catalog_bytes)
                verified = svc.stat(catalog_path).get('st_size')
                print(f'  저장: {len(catalog_bytes):,} bytes → {"OK" if verified == len(catalog_bytes) else "MISMATCH"}')

    print()
    if success:
        print('완료! 앱을 재시작해주세요.')
    else:
        print('일부 작업에 실패했습니다.')
        sys.exit(1)


if __name__ == '__main__':
    main()
