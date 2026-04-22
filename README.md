# pdf_to_script

PDF 슬라이드를 이미지로 변환하고, Gemini를 이용해 발표용 스크립트 마크다운을 생성하는 도구입니다.

## 실행 방법

### 1) Python 모듈로 실행

```bash
python -m cli <PDF파일경로>
```

예시:

```bash
python -m cli ./sample.pdf
```

페이지 범위 지정 예시:

```bash
python -m cli ./sample.pdf --start-page 3 --end-page 8
```

### 2) Windows 배치 파일로 실행

```bat
run.bat <PDF파일경로>
```

예시:

```bat
run.bat .\sample.pdf --verbose --log-file .\logs\run.log
```

## CLI 옵션

- `--output-dir <path>`: 출력 디렉터리 지정 (기본값: `output_<PDF파일명>`)
- `--start-page <int>`: 처리 시작 페이지 지정 (1부터 시작, 포함)
- `--end-page <int>`: 처리 종료 페이지 지정 (포함)
- `--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}`: 로그 레벨 지정 (기본값: `INFO`)
- `--log-file <path>`: 파일 로그 저장 경로
- `--verbose`: 디버그 로그 강제 출력 (`--log-level`보다 우선)
- `--quiet`: 경고/에러만 출력 (`--log-level`보다 우선)
- `--ca-bundle <pem>`: 사내 루트 인증서 PEM 경로를 SSL 인증서 경로로 지정
- `--insecure`: SSL 인증서 검증 비활성화(임시 테스트 용도)
- `--improve-with-claude`: Gemini 생성본을 Claude가 이미지+텍스트를 참고해 개선한 `*_claude.md` 추가 생성

기본적으로 같은 출력 파일이 이미 존재하면, 완료된 마지막 페이지(`---`로 닫힌 페이지)를 감지해 다음 페이지부터 이어서 생성합니다( `*_gemini.md`, `*_claude.md` 모두 동일).

## 출력 결과

- 이미지 폴더: `<output_dir>/images/slide_01.jpg` ...
- Gemini 스크립트 파일: `<output_dir>/<PDF파일명>_gemini.md`
- Claude 개선 파일(옵션): `<output_dir>/<PDF파일명>_claude.md`

## 환경 변수

- `.env` 파일 또는 시스템 환경 변수에 `GOOGLE_API_KEY`를 두거나, 루트의 `service_account.json`을 사용합니다.
- Claude 개선 옵션 사용 시 `.env` 또는 시스템 환경 변수에 `ANTHROPIC_API_KEY`가 필요합니다.
- Claude 모델 변경이 필요하면 `.env`에 `ANTHROPIC_MODEL`을 지정하세요 (기본값: `claude-3-5-sonnet-20241022`).

예시:

```env
GOOGLE_API_KEY=your_api_key_here
ANTHROPIC_API_KEY=your_claude_api_key_here
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
```

## 트러블슈팅 (SSL 인증서 오류)

`certificate verify failed`가 발생하면 사내 프록시/보안장비의 루트 인증서가 필요할 수 있습니다.

- 기본적으로 앱은 `certifi` CA 번들을 자동 설정합니다.
- 사내 인증서가 필요하면 아래 환경 변수를 지정해 실행하세요.

```bat
set REQUESTS_CA_BUNDLE=C:\path\to\corp-ca.pem
set SSL_CERT_FILE=C:\path\to\corp-ca.pem
run.bat .\sample.pdf
```

또는 CLI 옵션으로 직접 지정:

```bat
run.bat .\sample.pdf --ca-bundle C:\path\to\corp-ca.pem
```

`NO_CERTIFICATE_OR_CRL_FOUND` 오류가 나오면 지정한 파일이 PEM 형식이 아닐 가능성이 큽니다.
Windows에서 변환:

```bat
certutil -encode corp-ca.cer corp-ca.pem
run.bat .\sample.pdf --ca-bundle .\corp-ca.pem
```

임시 우회(보안 비권장):

```bat
run.bat .\sample.pdf --insecure
```

## Python 코드에서 재사용

```python
from config import GeneratorConfig
from generator import PresentationScriptGenerator

config = GeneratorConfig(temperature=0.2)
generator = PresentationScriptGenerator(config=config)
result_path = generator.process_presentation("sample.pdf")
print(result_path)
```
