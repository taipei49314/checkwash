# greenwash v0.1.49 — 外部實測總報告(最終版)

**日期**:2026-09-01 · **執行**:維護者本人(taipei49314),本機 Windows / Python 3.12,黑盒使用 release 單檔 `greenwash.pyz`,greenwash repo 本體未修改 · **判定**:單人判定(single-rater, preliminary)

## 總量

**13 個專案、2300 個人類審過的非 merge commit、74 個 block = 3.22%**
(扣除 in-corpus 的 rich 後:樣本外 12 專案 2200 commits、70 block = **3.18%**)
**引擎錯誤:0。崩潰:0。全部輸出確定性 JSON。**

## 全量數據

| # | 專案 | corpus? | block | 率 | 觸及測試 | opaque | 引擎錯 |
|---|---|---|---|---|---|---|---|
| 1 | psf/requests | 否 | 0/100 | 0.0% | 15 | 3 | 0 |
| 2 | willmcgugan/rich | **是** | 4/100 | 4.0% | 31 | 0 | 0 |
| 3 | pydantic/pydantic | 否 | 2/100 | 2.0% | 52 | 19 | 0 |
| 4 | fastapi/fastapi | 否 | 2/200 | 1.0% | 18 | 14 | 0 |
| 5 | aio-libs/aiohttp | 否 | 6/200 | 3.0% | 63 | 25 | 0 |
| 6 | celery/celery | 否 | 2/200 | 1.0% | 111 | 6 | 0 |
| 7 | psf/black | 否 | 16/200 | **8.0%** | 58 | 6 | 0 |
| 8 | httpie/httpie | 否 | 6/200 | 3.0% | 32 | 39 | 0 |
| 9 | twisted/twisted | 否 | 0/200 | **0.0%** | 73 | 5 | 0 |
| 10 | sqlalchemy/sqlalchemy | 否 | 2/200 | 1.0% | 106 | 10 | 0 |
| 11 | tornadoweb/tornado | 否 | 9/200 | 4.5% | 91 | 5 | 0 |
| 12 | sympy/sympy | 否 | 13/200 | 6.5% | 120 | 2 | 0 |
| 13 | pandas-dev/pandas | 否 | 12/200 | 6.0% | 145 | 54 | 0 |

## 三輪的主要發現

### 1. 誤擋集中於已命名家族,無未建模機制
74 個 block 的人工判定全部落在 THREATMODEL / DECISIONS 已記載的家族:
- **D-050 兩段式 split**(rich `823de916d9` 等 4 個)
- **THREATMODEL 92 單元重構 / D2 hash 級搬移信用**(pydantic `69fd688e2d` 拆檔 → 131 條 high;pandas `5fef3b9e11` 移除 assert_matching helper;tornado `d6e55b5a65` subprocess 化)
- **row 86 project-local base class**(black 的 `BlackBaseTestCase` + 自訂 helper,16/200 全源於此,同批 unit 跨 commit 反覆命中)
- **row 86a 期望值定義漂移**(httpie "Cleanup" 112 條;sympy assumptions 測試群)
- **斷言集體改寫**(sympy `bc87480ee6`「bare asserts 補訊息」、`a31843cd71`「ask→_ask_recursive」API 遷移 → ASSERT_WEAKENED/SUBSTITUTED 連發)
- **GUARDRAIL 按設計擋**(pandas `518f2a3cb9` 修改 AI 披露政策檔 → critical,屬設計內行為)

### 2. 兩個正向驗證
- **row 86b(unittest 方言盲區)沒有應驗**:unittest 文化最重的 twisted 是 **0/200**。原因事後看重很簡單——盲區在 `EXPECTED_VALUE_DERIVED` 一條規則,而該規則的觸發前提(literal→運算式轉變)在老派 unittest 倉庫裡本來就罕見。但這是量出來的,不是推測。
- **corpus-expansion 論題方向性成立**:誤擋率與「測試文化距離六專案 corpus 的遠近」強相關——black/sympy/pandas(helper 化、大規模重構、期望值集中管理)6–8%;requests/twisted/sqlalchemy(樸素測試)0–1%。

### 3. 疑似正確攔截(非誤擋)
- aiohttp `c52fe79c74` / `79b5f5fa5b`(fix flaky test,刪 timing/retry 斷言)— 依 SPEC 屬合法 policy block。
- sqlalchemy 兩個 `CI_WORKFLOW_TOUCHED` high 未細審,可能含真實 CI 弱化。

## 給維護者的成本排序(依實測價格)

1. **跨檔 / project-local base 的 oracle 解析**(row 86/91):單 black = 16 block/200 commits,是殘餘中最貴、也最集中的。
2. **整檔拆分 / helper 移除的搬移信用**(D2/D10 + row 92):pydantic 131 條、pandas/tornado 多個 block 的共同根因。
3. **斷言集體改寫的補償**(assert 加訊息、API 遷移):sympy 三個 commit ≈ 30+ 條,形狀接近 D4 但現行條件不涵蓋。
4. E6 / CI 家族:三輪 2300 commits 無新失誤,不用動。

## 方法限制(照自家規矩聲明)

單人判定、無第二評審、無 kappa;13 專案是便利抽樣非隨機;判定顆度:第 1、2 輪逐案看 diff,第 3 輪多數僅看 commit subject + finding 明細。若要進 `benchmarks/`,應視為 preliminary,需再過一輪正式 adjudication。

## 重現

```bash
curl -LO https://github.com/taipei49314/greenwash/releases/latest/download/greenwash.pyz
git clone --depth 250 <org>/<repo> && cd <repo>
python ../greenwash.pyz sweep HEAD --limit 200   # 本機執行,零網路、零 Actions 額度
```

原始數據:同目錄 13 份 `*_sweep.json`。
