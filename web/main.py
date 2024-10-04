from flask import Flask, render_template, request, redirect, jsonify, url_for
import subprocess
import os
import csv
import threading
import time

app = Flask(__name__)
# 전역 변수로 state_filename 설정
state_filename = 'state.csv'
running = False

# EPICS caput과 caget 명령어를 실행하는 함수
def run_epics_command(pv_name, value=None):
    try:
        if value:
            command = ['caput', pv_name, value]
        else:
            command = ['caget', pv_name]
        result = subprocess.run(command, stdout=subprocess.PIPE)
        output = result.stdout.decode('utf-8').strip()
        
        # caget 실패 시 None 반환
        if output == '' or 'not found' in output:
            return None
        return output.split()[-1]
    except Exception as e:
        return None


# CSV 파일 불러오거나 없으면 생성하는 함수
def get_or_create_csv(experiment_number):
    filename = f"experiment_{experiment_number}.csv"
    if not os.path.exists(filename):
        with open(filename, 'w', newline='') as file:
            writer = csv.writer(file)
            # 헤더 생성
            writer.writerow(["SV PV", "SV", "RV PV", "HH", "High", "Low", "LL", "AlarmActive", "ErrorRate"])
    return filename

# state.csv 파일에서 실험 상태와 실험 번호를 읽어오는 함수
def get_or_create_experiment_state():
    state_filename = 'state.csv'
    
    # state.csv 파일이 없거나 내용이 잘못되었을 때 기본 값으로 생성
    if not os.path.exists(state_filename) or not is_valid_state_csv(state_filename):
        with open(state_filename, 'w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([1, 0])  # 기본값: 실험 번호 1, 상태는 정지(0)

    # state.csv 파일을 읽어옴
    with open(state_filename, 'r') as file:
        reader = csv.reader(file)
        state = next(reader)  # 첫 번째 줄 읽기
        experiment_number = int(state[0])  # 첫 번째 셀: 실험 번호
        experiment_status = int(state[1])  # 두 번째 셀: 실험 상태 (1: 실행, 0: 정지)

    return experiment_status, experiment_number

# state.csv 파일이 올바른지 검증하는 함수
def is_valid_state_csv(filename):
    try:
        with open(filename, 'r') as file:
            reader = csv.reader(file)
            state = next(reader)
            # 첫 번째 셀과 두 번째 셀이 모두 숫자인지 확인
            int(state[0])
            int(state[1])
        return True
    except (ValueError, IndexError, StopIteration):
        return False

 

# 실험 루프 실행 함수
def experiment_loop():
    global running
    while running:
        state, experiment_number = get_state()
        if state == 1:
            # state.csv에 저장된 값으로 caput 실행
            filename = f'experiment_{experiment_number}.csv'
            if os.path.exists(filename):
                with open(filename, 'r') as file:
                    reader = csv.reader(file)
                    data = list(reader)[1:]  # 첫 번째 줄은 헤더이므로 제외
                    for row in data:
                        sv_pv = row[0]
                        sv = row[1]
                        run_epics_command(sv_pv, sv)  # caput 실행
        time.sleep(2)  # 2초마다 반복

# 실험 정지 엔드포인트
@app.route('/stop_experiment', methods=['POST'])
def stop_experiment():
    try:
        data = request.get_json()
        experiment_number = data['experiment_number']
        
        # 상태를 정지로 설정 (state.csv에서 1번째 셀에 0 저장)
        update_experiment_state(experiment_number, 0)  # 상태를 0으로 설정 (정지)
        
        return jsonify({'success': True})
    except Exception as e:
        print(f"Error stopping experiment: {e}")
        return jsonify({'success': False, 'error': str(e)})

# state.csv 파일에서 실험 상태 및 번호를 불러오는 함수
def get_experiment_state():
    filename = "state.csv"
    if not os.path.exists(filename):
        with open(filename, 'w', newline='') as file:
            writer = csv.writer(file)
            # 초기 상태: 1번 실험, 정지 상태 (실험 번호, 상태)
            writer.writerow([1, 0])
    
    with open(filename, 'r') as file:
        reader = csv.reader(file)
        return list(reader)[0]  # [실험 번호, 상태]

# state.csv 파일에 실험 상태 업데이트 함수
def update_experiment_state(experiment_number, status):
    filename = "state.csv"
    with open(filename, 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([experiment_number, status])  # 실험 번호, 상태(1: 실행, 0: 정지)



# 서버 상태를 읽어오는 API
@app.route('/get_experiment_state', methods=['GET'])
def get_experiment_state():
    try:
        state, experiment_number = get_state()  # 이 함수는 올바른 state와 experiment_number를 가져온다고 가정
        return jsonify({
            "status": state, 
            "experiment_number": experiment_number
        })  # JSON 형태로 상태와 실험 번호 반환
    except Exception as e:
        return jsonify({"error": str(e)}), 500  # 에러 발생 시 JSON 형태로 에러 메시지 반환



# 기본 페이지 - 실험 번호 입력
@app.route('/')
def index():
    return render_template('index.html')


# PV 모니터 페이지
@app.route('/experiment')
def experiment():
    experiment_number = request.args.get('experiment_number', '1')
    filename = f'experiment_{experiment_number}.csv'
    data = []
    
    if os.path.exists(filename):
        with open(filename, 'r') as file:
            reader = csv.reader(file)
            data = list(reader)[1:]  # 첫 번째 줄은 헤더이므로 제외

    state, _ = get_state()
    return render_template('experiment.html', experiment_number=experiment_number, data=data, state=state)

# Alarm 상태 계산 함수
def calculate_alarm_state(hh, high, low, ll, alarm_active, rv):
    try:
        if rv is None or rv == '':
            return 0  # 오류가 있으면 기본 상태
        if alarm_active == '1':
            rv = float(rv)
            if rv > float(hh):
                return 5  # 빨강
            elif rv > float(high):
                return 4  # 주황
            elif rv < float(ll):
                return 2 # 파랑 
            elif rv < float(low):
                return 3  # 하늘 
        return 1  # 정상 상태
    except ValueError:
        return 6  # 변환 오류 시 기본 상태

# PV 모니터 페이지
@app.route('/pv_monitor', methods=['GET', 'POST'])
def pv_monitor():
    experiment_number = request.args.get('experiment_number', '1')  # 기본값 1
    filename = get_or_create_csv(experiment_number)

    with open(filename, 'r') as file:
        reader = csv.reader(file)
        data = list(reader)

    # 데이터를 테이블로 변환 (실시간 caget 값을 반영)
    table_data = []
    for row in data[1:]:
        sv_pv = row[0]
        rv_pv = row[2]
        
        # 실시간으로 SV와 RV 값을 caget으로 읽어옴
        r_sv = run_epics_command(sv_pv)
        r_rv = run_epics_command(rv_pv)

        # 알람 상태 계산
        alarm_state = calculate_alarm_state(row[3], row[4], row[5], row[6], row[7], r_rv)

        table_data.append({
            "sv_pv": sv_pv,
            "sv": row[1],
            "r_sv": r_sv,
            "rv_pv": rv_pv,
            "r_rv": r_rv,
            "hh": row[3],
            "high": row[4],
            "low": row[5],
            "ll": row[6],
            "alarm_state": alarm_state
        })

    return render_template('pv_monitor.html', data=table_data, experiment_number=experiment_number)

# CSV 파일에서 특정 행을 삭제하는 함수
@app.route('/delete', methods=['POST'])
def delete_row():
    experiment_number = request.form['experiment_number']
    row_index = int(request.form['row_index'])  # 삭제할 행의 인덱스
    
    filename = get_or_create_csv(experiment_number)

    # CSV 파일에서 해당 행 삭제
    with open(filename, 'r') as file:
        rows = list(csv.reader(file))

    if row_index < len(rows):
        del rows[row_index]  # 해당 인덱스의 행 삭제

    # 변경된 데이터를 다시 CSV에 저장
    with open(filename, 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerows(rows)

    return redirect(f'/load?experiment_number={experiment_number}', code=302)

# state.csv 파일에서 상태 읽기
# state.csv 파일에서 실험 상태 및 번호를 불러오는 함수
def get_state():
    filename = 'state.csv'
    
    # 파일이 없으면 기본 값을 생성
    if not os.path.exists(filename):
        with open(filename, 'w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([1, 0])  # 기본값: 실험 번호 1, 정지 상태
    
    with open(filename, 'r') as file:
        reader = csv.reader(file)
        state = next(reader, None)
        
        if state is None or len(state) < 2:
            # 값이 비어있거나 잘못된 경우 기본값 반환
            return 0, 1
        
        try:
            experiment_number = int(state[0]) if state[0] else 1  # 기본 실험 번호: 1
            experiment_status = int(state[1]) if state[1] else 0  # 기본 상태: 정지(0)
        except ValueError:
            # 값 변환 중 문제가 생기면 기본값 반환
            return 0, 1

        return experiment_status, experiment_number

# state.csv 파일에 상태 저장
def set_state(status, experiment_number):
    with open(state_filename, 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([status, experiment_number])


# 실시간 PV 데이터를 가져오는 API 엔드포인트
@app.route('/get_monitor_data', methods=['GET'])
def get_monitor_data():
    experiment_number = request.args.get('experiment_number', '1')
    filename = f"experiment_{experiment_number}.csv"

    if not os.path.exists(filename):
        return jsonify({"error": "CSV 파일이 존재하지 않습니다."})

    with open(filename, 'r') as file:
        reader = csv.reader(file)
        data = list(reader)

    # 데이터를 테이블로 변환하여 반환
    table_data = []
    for row in data[1:]:
        r_sv = run_epics_command(row[0])  # SV PV 값을 읽어옴
        r_rv = run_epics_command(row[2])  # RV PV 값을 읽어옴
        alarm_state = calculate_alarm_state(row[3], row[4], row[5], row[6], row[7], r_rv)
        
        table_data.append({
            "sv_pv": row[0],
            "sv": row[1],
            "rsv": r_sv,
            "rv_pv": row[2],
            "rv": r_rv,
            "hh": row[3],
            "high": row[4],
            "low": row[5],
            "ll": row[6],
            "alarm_state": alarm_state
        })
    sorted_data = sorted(table_data, key=lambda x: x['alarm_state'], reverse=True)

    return jsonify(sorted_data)

# 실험 실행/정지 엔드포인트
@app.route('/start_experiment', methods=['POST'])
def start_experiment():
    global running
    data = request.json
    experiment_number = data.get('experiment_number')

    if experiment_number is None:
        return jsonify({"success": False, "error": "실험 번호가 제공되지 않았습니다."})

    # 실험 상태 업데이트
    set_state(1, experiment_number)  # 1: 실행 상태로 업데이트
    if not running:
        running = True
        threading.Thread(target=experiment_loop).start()
    
    return jsonify({"success": True})


# 실시간 결과 가져오기
@app.route('/get_results', methods=['POST'])
def get_results():
    global running
    if running:
        results = next(run_experiment_loop())
        return jsonify(results)
    else:
        return jsonify({"status": "실험 중이 아님"})


# CSV 파일에서 실험 데이터를 불러오는 함수
@app.route('/load', methods=['GET', 'POST'])
def load_file():
    if request.method == 'POST':
        experiment_number = request.form.get('experiment_number') or '1'  # POST 요청에서 'experiment_number' 받아오기, 없으면 기본값 1
    else:
        experiment_number = request.args.get('experiment_number') or '1'  # GET 요청일 경우 'experiment_number' 받아오기, 없으면 기본값 1

    if not experiment_number:
        return "실험 번호가 필요합니다.", 400  # 실험 번호가 없으면 오류 메시지 출력

    filename = get_or_create_csv(experiment_number)

    # CSV 파일이 비어있을 때 빈 데이터를 반환
    try:
        with open(filename, 'r') as file:
            reader = csv.reader(file)
            data = list(reader)
    except Exception as e:
        data = []

    # 만약 파일에 데이터가 없으면 헤더만 출력 (빈 테이블)
    if len(data) == 0:
        data.append(["SV PV", "SV", "RV PV", "HH", "High", "Low", "LL", "AlarmActive", "ErrorRate"])

    # enumerate를 템플릿으로 넘겨줌
    return render_template('file_view.html', data=data, experiment_number=experiment_number, enumerate=enumerate)

# CSV 파일에 데이터 추가
@app.route('/add', methods=['POST'])
def add_row():
    experiment_number = request.form['experiment_number']
    sv_pv = request.form['sv_pv']
    sv = request.form['sv']
    rv_pv = request.form['rv_pv']
    hh = request.form['hh']
    high = request.form['high']
    low = request.form['low']
    ll = request.form['ll']
    alarm_active = request.form['alarm_active']
    error_rate = request.form['error_rate']

    # 입력 값 검증
    if alarm_active not in ['0', '1']:
        return "AlarmActive 값은 0 또는 1이어야 합니다."
    if not (0 <= float(error_rate) <= 100):
        return "Error Rate 값은 0부터 100 사이여야 합니다."

    filename = get_or_create_csv(experiment_number)

    # CSV 파일에 데이터 추가
    with open(filename, 'a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([sv_pv, sv, rv_pv, hh, high, low, ll, alarm_active, error_rate])

    return redirect(f'/load?experiment_number={experiment_number}', code=307)


if __name__ == '__main__':
    app.run(debug=True)
