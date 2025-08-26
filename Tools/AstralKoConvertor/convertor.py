import json
import os
import sys

def select_file_from_list(extension: str, folder_path: str) -> str:
    """
    지정된 폴더에서 주어진 확장자를 가진 파일 목록을 보여주고,
    사용자가 하나를 선택하게 하여 전체 경로를 반환합니다.
    """
    # 1. 지정된 폴더가 있는지 확인
    if not os.path.isdir(folder_path):
        print(f"[WRONG] '{folder_path}' 폴더를 찾을 수 없습니다. 프로그램을 종료합니다.")
        sys.exit()

    # 2. 폴더 내에서 해당 확장자를 가진 파일 검색
    files = [f for f in os.listdir(folder_path) if f.endswith(extension)]

    if not files:
        print(f"[WRONG] '{folder_path}' 폴더에 {extension} 파일이 없습니다. 프로그램을 종료합니다.")
        sys.exit()

    print(f"\n--- [{os.path.join(extension)} 파일 선택] ---")
    for i, filename in enumerate(files, 1):
        print(f"[{i}] {filename}")

    while True:
        try:
            choice = int(input(f"사용할 파일의 번호를 입력하세요 (1-{len(files)}): "))
            if 1 <= choice <= len(files):
                selected_file = files[choice - 1]
                # 파일명만이 아닌 전체 경로를 반환
                full_path = os.path.join(folder_path, selected_file)
                print(f"[INFO] '{full_path}' 파일을 선택했습니다.")
                return full_path
            else:
                print(f"[WRONG] 잘못된 번호입니다. 1에서 {len(files)} 사이의 숫자를 입력하세요.")
        except ValueError:
            print("[WRONG] 숫자로만 입력해주세요.")


# --- 파일 경로 설정 (지정 폴더 내에서 자동 감지 및 사용자 선택) ---

dat_folder = '01_dat'
json_folder = '02_json'

# 1. 원본 .dat 파일 선택 ('dat' 폴더)
dat_file_path = select_file_from_list('.dat', dat_folder)
# 출력 파일명을 만들기 위해 경로와 확장자를 제외한 순수 파일명 추출
dat_filename_base = os.path.splitext(os.path.basename(dat_file_path))[0]


# 2. 번역 데이터가 포함된 .json 파일 선택 ('json' 폴더)
json_file_path = select_file_from_list('.json', json_folder)

# 3. 수정된 내용을 저장할 새 바이너리 파일 경로 설정
output_dir = '03_convert'
dat_output_path = f"{dat_filename_base}_ko.dat"
output_dat_file_path = os.path.join(output_dir, dat_output_path)

# 'convert' 폴더가 없으면 자동으로 생성
if not os.path.exists(output_dir):
    os.makedirs(output_dir)
    print(f"\n'[INFO] {output_dir}' 폴더를 생성했습니다.")

# --- 작업 결과를 기록할 리스트 ---
not_found_in_dat = []    # .dat 파일에서 원문(ja)을 찾지 못한 경우
kr_text_too_long = []    # 번역문(kr)이 원문보다 길어 교체하지 못한 경우
kr_text_empty = []       # 번역문(kr)이 비어있어 건너뛴 경우

try:
    # 1. .dat 파일을 바이너리 모드로 미리 읽기
    with open(dat_file_path, 'rb') as f:
        dat_content = f.read()

    # 2. JSON 파일을 열고, (ja_bytes, kr_string) 쌍의 리스트 생성
    with open(json_file_path, 'r', encoding='utf-8') as f:
        translations = json.load(f)

    binary_translation_pairs = []
    for item in translations:
        ja_text = item.get('ja')
        if ja_text: # ja 값이 있는 경우에만 처리
            kr_text = item.get('kr', '') # kr 값이 없으면 빈 문자열로 처리
            ja_bytes = ja_text.encode('utf-8')
            binary_translation_pairs.append((ja_bytes, kr_text))

    # 3. 'ja' 바이너리의 길이를 기준으로 리스트를 내림차순 정렬
    sorted_pairs = sorted(binary_translation_pairs, key=lambda pair: len(pair[0]), reverse=True)

    # 4. 정렬된 순서대로 .dat 파일 내용 교체
    for ja_bytes, kr_text in sorted_pairs:
        if ja_bytes not in dat_content:
            not_found_in_dat.append(ja_bytes)
            continue

        if not kr_text:
            kr_text_empty.append(ja_bytes)
            continue
            
        kr_bytes = kr_text.encode('utf-8')

        if len(kr_bytes) > len(ja_bytes):
            kr_text_too_long.append(ja_bytes)
            continue

        padding_needed = len(ja_bytes) - len(kr_bytes)
        padded_kr_bytes = kr_bytes + (b'\x00' * padding_needed)

        dat_content = dat_content.replace(ja_bytes, padded_kr_bytes)

    # 5. 수정된 내용으로 새 .dat 파일 저장
    with open(output_dat_file_path, 'wb') as f:
        f.write(dat_content)

    print(f"\n[INFO] 파일 수정 완료! 결과물이 '{output_dat_file_path}'에 저장되었습니다.")

    # 6. 처리 실패 요약 출력
    print("\n--- 실패 내용 요약 ---")
    if not_found_in_dat:
        print(f"\n[.dat 파일에서 찾지 못한 원문(ja) - {len(not_found_in_dat)}개]")
        for b in not_found_in_dat:
            print(f"- {b.decode('utf-8', 'ignore')}")

    if kr_text_too_long:
        print(f"\n[번역문(kr)이 원문(ja)보다 길어서 건너뛴 항목 - {len(kr_text_too_long)}개]")
        for b in kr_text_too_long:
            print(f"- {b.decode('utf-8', 'ignore')}")

    if kr_text_empty:
        print(f"\n[번역문(kr)이 비어있어 건너뛴 항목 - {len(kr_text_empty)}개]")
        for b in kr_text_empty:
            print(f"- {b.decode('utf-8', 'ignore')}")

except FileNotFoundError as e:
    print(f"[ERROR] 파일을 찾을 수 없습니다. ({e.filename})")
except json.JSONDecodeError:
    print(f"[ERROR] '{json_file_path}' 파일이 올바른 JSON 형식이 아닙니다.")
except Exception as e:
    print(f"[ERROR] 알 수 없는 오류가 발생했습니다: {e}")