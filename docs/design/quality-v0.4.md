# Checkwash v0.4 品質驗收弱化偵測完整規格提案

文件日期：2026-09-09  
文件版本：提案 1.0  
狀態：可供實作拆票與維護者審查的設計稿，尚未成為專案政策或已發布能力。  
對象：產品負責人、維護者、實作者與驗收者。

本版目標是讓 reviewer 看見：一個 PR 是否降低了覆蓋率要求、停用了品質規則，或讓既有程式碼退出檢查範圍。保留 Checkwash 對已知模式的、有邊界的靜態分析方式。首版支援 coverage.py、Ruff、mypy 的明列子集；不宣稱證明程式正確、判定作者動機，或證明 CI 實際執行了這些要求。

本文中的 MUST 表示本提案的必要實作條件；SHOULD 表示偏離時須記錄理由。以下版本號、規則 ID、CLI 與 schema 都是新增設計，現版不能直接執行。

## 1 版本基線與已確認事實

設計基線固定為 Checkwash main commit `387e71befedc387ab0c85af4c3322b7877a0cfd1`，於 2026-09-09 讀取。以該 commit 的原始檔為準，不以本機較舊 checkout 推定現況。

| 項目 | 已確認基線 | 本提案處理 |
|---|---|---|
| 發布 | STATE 記錄 CLI v0.3.3、發布後恢復凍結 | v0.4 為規劃名稱，沒有排程發布或解除凍結 |
| 現有檢查 | 測試弱化、部分 CI 弱化、suppression 與 guardrail 變更 | 不把這些重新計為新增功能 |
| 信任 | 政策與豁免讀 base；head 為待審資料 | 沿用信任方向 |
| 分析方式 | 本機、核心不連網、不執行受分析專案 | 新能力維持此條件 |
| 現有輸出 | findings schema 2；四級 severity；退出碼 0／1／2 | 保留既有 check 的輸出與退出碼合約 |

來源：[固定基線 README](https://github.com/taipei49314/checkwash/blob/387e71befedc387ab0c85af4c3322b7877a0cfd1/README.md)、[STATE](https://github.com/taipei49314/checkwash/blob/387e71befedc387ab0c85af4c3322b7877a0cfd1/STATE.md)、[SPEC](https://github.com/taipei49314/checkwash/blob/387e71befedc387ab0c85af4c3322b7877a0cfd1/SPEC.md)。

產品對外描述建議：**「檢查 PR 是否放寬原本的品質驗收要求。」**

範例 finding：`coverage.report.fail_under 從 85 降到 50；在所宣告的設定模型下，覆蓋率門檻降低。`

不得寫成：「這個 PR 已經作弊」「CI 一定被繞過」「沒報警就代表所有要求都保住了」。

## 2 核心使用情境

| 情境 | 使用者需要知道 | 期望結果 |
|---|---|---|
| 修 bug 同時降低 coverage 門檻 | 改了多少、哪裡改、是否有核准 | 明確呈現門檻變化 |
| 新增 lint ignore | 哪些原本啟用的規則退出要求 | 列出具體 rule code，不以 ignore 數量推定 |
| mypy strict 被停用 | 子旗標有沒有補回原先要求 | 模型充分時逐項比較；不充分時要求審查 |
| 排除核心程式目錄 | 哪些仍存在的既有檔案不再納入 | 提供路徑證據與分析邊界 |
| 設定搬家或整理 | 是否只是位置、格式改變 | 語意等價不產生弱化 finding |
| 合法降低標準 | 如何使 reviewer 明確核准 | 使用內容綁定豁免，不以修改量或 production cochange 自動消音 |
| 解析遇到不支援語法 | 哪些項目未完成分析 | 保留已證明結果，同時列明 incomplete |

## 3 範圍與交付決定

### 3.1 v0.4 必做

1. 新增獨立 `checkwash quality` 命令與版本化 quality 報告。
2. 新增共用快照讀取、設定來源解析、差異模型、內容指紋與完整性狀態。
3. coverage.py：整數 coverage 門檻下降，以及有限路徑排除範圍比較。
4. Ruff：版本模型內的規則集合損失，以及有限路徑排除範圍比較。
5. mypy：版本模型內的全域檢查旗標與錯誤碼停用；strict 展開不充分時只出審查事件。
6. 三個工具的正常變更、弱化變更、不支援輸入測試矩陣。
7. report 與 enforce 兩種模式；預設 report，enforce 需要已存在 base 的目標設定。

三個 adapter 都必須有可用的最小子集才符合本版完整交付。若只完成 coverage.py，可標成 preview，不得宣稱本提案全部完成。

### 3.2 本版不做

- 一般 shell、GitHub Actions YAML、任意 CI graph 的完整執行語意分析。
- 查驗線上 branch protection、required checks、工具是否真的執行。
- 安全掃描器 baseline、自訂品質評分、LLM benchmark、報告真偽驗證。
- mypy 任意 module override、任意 regex 的等價／包含證明。
- 自動修復、自動更新豁免、自動降低 severity。
- SaaS、儀表板、LLM judge、新 repository。

這些不是隱藏的後續相依條件；首版驗收不得要求先完成它們。

## 4 判決的證據層次

每個事件 MUST 區分三種主張：

| 層次 | 可以主張 | 不可以主張 |
|---|---|---|
| `declaration` | 某設定鍵、規則列表或排除宣告改變了 | 這一定改變實際檢查結果 |
| `resolved_config` | 在已宣告 target 與已驗證 adapter 模型內，有效設定少了一項要求 | CI 一定採用該 target |
| `execution` | 本版不產出此層次 | 不得把前兩者升格為執行證據 |

**target 是維護者在 base 宣告的分析情境，不是 CI 執行證明。** 報告永遠包含 `activation_evidence: "declared_only"`。

對每一個獨立檢查維度，計算 `equal / strengthened / weakened / incomparable / unknown`。不同維度不能互相抵銷：啟用新的 lint 規則，不會自動補償被關掉的舊規則；coverage 門檻提高，也不會消除排除目錄造成的 finding。

正當政策調整與偵測誤報 MUST 分開標籤。正當調整仍可能真的降低要求；工具正確報出這件事，不等於誤報。

## 5 信任與來源規格

### 5.1 雙快照

- 分別從 base、head 的樹讀取完整相關設定。不得只從 diff 行推導有效設定。
- Git range 與 worktree 取樣方式沿用既有 reader；quality 不另造較寬鬆的 Git 路徑。
- base 的 `.checkwash/quality.toml` 決定模式、targets、adapter profiles；head 同名檔只作為變更證據。
- base 無 quality.toml 時為探索模式，只能 report。head 新增的政策不能替本 PR 啟用、關閉或選擇有利的分析規則。
- target 的外部工具設定是「受比較資料」，因此兩邊都讀；不能因為 head 不可信就完全不讀它。

### 5.2 目標設定來源

target 可指定 `config = "repo/relative/file"`，或使用 `config = "auto"` 與明確 `root`。自動模式只按 adapter 已驗證的搜尋順序解析 repo 內設定；不存在可用模型時回報 unknown。

每個 snapshot 獨立計算：候選檔 → 優先順序 → 選中來源 → 繼承來源 → 關聯覆寫 → 有效值。高優先設定檔的新增／刪除、未改動 parent 的變更，以及 nested 設定的遮蔽，都是分析相依性。

不得讀取 home、使用者全域設定、host 環境變數、網路 extend 或 repo 外檔案。含 `${VAR}`、外部路徑、未支援替換形式時，受影響維度變為 unknown；不以空字串或預設值代替。

### 5.3 指紋綁定的來源證據

每個結果記錄所有影響該結論的設定來源與 CRLF→LF 後 SHA256。還須綁定 discovery inventory：例如先前不存在、現在新增的較高優先設定檔。只 hash「被選中的檔案」不足以保護設定選擇本身。

相依性只取真正影響該事件的部分；repo 中無關 README 變更不能使所有豁免失效。

### 5.4 目標變更與版本變更

- 同一 PR 改 head target、mode、profile，當次仍使用 base 宣告，並產生明顯政策變更事件。
- 不從執行中的 Python 環境自動猜外部工具版本。
- profile 使用精確版本與模型 digest；不使用 `latest` 或寬鬆版本範圍作為證明依據。
- target 可宣告 tracked `version_files` 作為版本來源監視清單。檔案變更且無法證明相關工具版本未變，該 target 在 enforce 下 incomplete。
- 未宣告完整 runtime 版本來源時，報告寫明版本為維護者宣告假設。不可因此宣稱真實 CI 版本已驗證。

## 6 設定與 CLI 合約

### 6.1 建議新增設定

```toml
# .checkwash/quality.toml，以下為未實作的提案格式
schema_version = 1
mode = "report"  # report | enforce

[[targets]]
id = "coverage-main"
tool = "coverage"
root = "."
config = "pyproject.toml"
profile = "coverage-qualified-profile-id"
version_files = ["uv.lock"]
paths = ["src/"]

[[targets]]
id = "ruff-main"
tool = "ruff"
root = "."
config = "auto"
profile = "ruff-qualified-profile-id"
version_files = ["uv.lock"]
paths = ["src/", "tests/"]

[[targets]]
id = "mypy-main"
tool = "mypy"
root = "."
config = "pyproject.toml"
profile = "mypy-qualified-profile-id"
version_files = ["uv.lock"]
paths = ["src/"]
```

範例 profile ID 是佔位符，不是已存在的 adapter；實作第一階段由資格驗證產出可用 ID。`paths` 僅接受 repo 相對檔案或以 `/` 結尾的目錄，不接受自訂 glob，避免再增加一套含混語法。目錄按 segment 前綴展開。

config 必填；`auto` 是明確選項。id 必須唯一且符合 `[a-z0-9][a-z0-9_-]{0,63}`。root 必須是 repo 內目錄。未知頂層鍵、錯字、錯誤型別、重複 id、空 targets 都是政策錯誤，不靜默忽略。base 完全沒有政策與「有政策但無有效 targets」不同。

v0.4 不提供每條規則 disable、severity 自訂或全域路徑豁免。先讓 profile 與內容豁免維持可審查範圍。

### 6.2 命令

```text
checkwash quality BASE...HEAD
checkwash quality BASE..HEAD --format json
checkwash quality --format sarif
checkwash quality profiles
checkwash quality explain QW_THRESHOLD_LOWERED
```

無 range 時沿用現有 worktree 比較語意，涵蓋其 reader 能見到的未追蹤設定候選。若 inventory 在兩次讀取間變動，當次 error，要求重跑。

模式只由 base 政策控制。v0.4 不提供 `--no-quality`、`--report-only` 或其他能在受保護執行中降級 base enforce 的 CLI 旗標。任意選擇 base 本身仍由呼叫端負責；CI 必須使用可信的 PR base/head refs，不能允許受審程式自由選擇比較範圍。

`quality profiles` 列出內建模型 ID、精確版本、支援鍵與 profile digest；不下載套件、不執行外部工具。`quality explain` 顯示規則、例子、支持範圍與已知限制。

### 6.3 完整性、severity 與退出碼

每個 target 有 `complete / partial / unsupported / error`。complete 只表示「本版承諾的維度已處理完」，不表示工具全部選項均支援。另列 `checked_dimensions` 與 `unsupported_dimensions`。

| 情況 | report | enforce |
|---|---|---|
| 完整且無未豁免弱化 | exit 0，`no_blocking_finding` | exit 0，`no_blocking_finding` |
| 有未豁免 high／critical，包括自身政策變更 | exit 0，`reported`，finding severity 不變 | exit 1，`block` |
| 未支援語意／超出確定性上限 | exit 0，`incomplete`，醒目警告 | exit 2，`incomplete` |
| 政策錯誤、選定來源毀損、I/O 錯誤、內部例外 | exit 2，`error` | exit 2，`error` |

優先順序：硬錯誤 > enforce incomplete > block > report incomplete > reported > no_blocking_finding。任何情況都保留其他已產生 findings。enforce 下不可把 unknown 當成「已證明弱化」而 exit 1；它是未完成判斷而 exit 2。

high 不等於在 report 模式阻擋，mode 決定執行效果。terminal 第一行 MUST 同時顯示 mode、verdict、完整性。CI 不應把 report exit 0 當成防護已部署。

## 7 規則目錄

| ID | 事件 | severity | 證據需求 |
|---|---|---|---|
| QW_THRESHOLD_LOWERED | 可比較 coverage 門檻下降 | high | resolved_config、前後值、相同量測條件 |
| QW_RULE_DISABLED | 舊有啟用規則／檢查旗標退出有效要求 | high | resolved_config、具體規則損失 |
| QW_SCOPE_NARROWED | 仍存在的既有路徑退出檢查集合 | high | resolved_config、至少一個受影響 witness |
| QW_POLICY_CHANGED | 相關宣告改變，但不能證明是放寬，或 Checkwash target 政策被修改 | warn；自身政策變更為 critical | declaration、變更摘要、不能判定原因 |
| QW_ANALYSIS_INCOMPLETE | 承諾分析的維度未完成 | warn | 原因碼、受影響 target／維度 |

POLICY_CHANGED 的 warn 不自行阻擋；若原因涉及無法解析的重要語意，同時產生 INCOMPLETE 並依模式處理。自身政策變更 critical 在 enforce 模式為 block；新政策一律不在當次採用。單純 append 新 target 也是可見政策變更，不私自當成擴大保護便自動放行。

不得將 production cochange、同 PR 修 bug、增加測試數量、提高其他門檻，當成上述三條 high 規則的降級理由。這是新規則的獨立判斷，不修改現有 oracle 規則的 repair-evidence 行為。

## 8 coverage.py adapter

### 8.1 已核對的工具特性

coverage 有多個設定來源；fail_under 的小數解讀受 precision 影響，run 與 report 的 omit 也屬不同階段。首版不能把它們壓成單一數值與單一 exclude 集合。[官方設定參考](https://coverage.readthedocs.io/en/latest/config.html)

### 8.2 首版支援

- TOML 與 INI 設定來源由 profile 列出，包括 pyproject、.coveragerc、setup.cfg、tox.ini；`.coveragerc.toml` 只在該精確版本實測支援時納入。
- `report.fail_under`：0–100 的整數值；`85` 與 `85.0` 正規化相同。
- 前後 `precision`、branch 量測設定及其他影響比較前提均已知且相同時，才作 threshold 判斷。
- 門檻鍵刪除：只有 profile 已證明缺省值，且來源解析完成時，才以有效預設比較。
- `run.omit`、`report.omit`：分階段比較；首版僅資格驗證過的 literal path 與簡單路徑 pattern 子集。

### 8.3 規則

設整數門檻為 b、h：h < b 產生 THRESHOLD_LOWERED；h = b 不報；h > b 記錄 strengthened 的分析摘要，不產生弱化 finding。

`85 → 50`：high。`85 → 刪除`：若有效值回到 0，high。`85 → 85.0`：不報。只移動設定且有效來源等價：不報。

小數非整數、precision 變動、branch true→false、source/include 設定變動、動態插值、未知 report 覆寫：產生 POLICY_CHANGED，受影響比較 incomplete，不武斷推導「數字更低所以更弱」。例如提高門檻但同時改量測方式，兩者不能直接相抵。

`exclude_lines`、`exclude_also` 等任意 regex 變化首版只出宣告變更與 incomplete；不執行受審 regex 來推論完整檢查範圍。

### 8.4 路徑 witness

從前後都存在的 tracked 檔案 U，計算各階段設定選取集合 S_b、S_h；L = S_b − S_h。L 非空才產生 SCOPE_NARROWED。報告說「設定範圍移除這些檔案」，不說「覆蓋率增加了多少」，因為本版不讀真實 coverage data。

沒有 witness 的新增排除，只產生 POLICY_CHANGED，內容說明可能影響未來檔案。它不是已證明無影響。刪除 production 檔案不會因已不存在的檔案而製造 scope-loss witness。

## 9 Ruff adapter

### 9.1 已核對的工具特性

Ruff 設定具有檔案優先順序、目錄作用範圍與 extend；命令列也可覆寫設定。規則前綴和選取／忽略不能用列表長度判斷。[官方設定解析](https://docs.astral.sh/ruff/configuration/)、[設定選項](https://docs.astral.sh/ruff/settings/)

### 9.2 首版支援

- `.ruff.toml`、`ruff.toml`、pyproject 中的 Ruff 設定區塊。
- repo 內 literal `extend`，深度上限見資源限制；循環／repo 外繼承不獲比較證明。
- `lint.select`、`lint.extend-select`、`lint.ignore`，以及 profile 明列且驗證的舊鍵別名。
- 一個 profile 的內建 rule catalog，前綴展開後比較具體 rule codes。
- `exclude`、`extend-exclude` 的已驗證 path subset。nested 設定完整發現後，按作用區域分開比較。

### 9.3 規則

以每個作用區域的有效規則集 R_b、R_h 計算 R_b − R_h。非空產生 RULE_DISABLED，列出 lost rules 及來源。集合比較可同時出現 lost 與 gained；gained 不能抵銷 lost。

以下反例 MUST 測試：原本沒開的規則加入 ignore，不是損失；select 語法換寫但展開集合一樣，不是損失；ignore 與更具體 select 的優先關係，必須依 profile 實測模型計算。

`per-file-ignores`、`extend-per-file-ignores`、preview、未知 rule code、規則重新命名、與目標語意相關但未建模的選項，在首版不授予完整解析。已存在的未支援選項若能影響該維度，也必須標示 incomplete，不能只檢查「是否本次新增」。

未知 code 不當作空集合。Ruff 本身沒有通用 `error → off` 的 severity 設定模型；產品示例應使用實際選取與 ignore 變更。

### 9.4 檢查範圍

按每個 target 與區域，使用共同存在檔案集計算 scope witness。不同工具的 glob 實作不能共用 Checkwash 既有角色 fnmatch 當成正確等價物。gitignore 與顯式檔案傳入會影響檔案發現；若 profile 未建模，報告須限制為所宣告的靜態 paths 模型，或將有衝突的維度標為 incomplete。

## 10 mypy adapter

### 10.1 已核對的工具特性

mypy strict 是多個旗標的組合，組成會隨版本改變；module overrides 與 inline 設定也有優先順序。首版必須限制比較範圍。[官方設定參考](https://mypy.readthedocs.io/en/stable/config_file.html)

### 10.2 首版支援

- `mypy.ini`、`.mypy.ini`、pyproject 與 setup.cfg 的全域設定，來源優先規則由 profile 驗證。
- 起始旗標集合：`disallow_untyped_defs`、`check_untyped_defs`、`disallow_incomplete_defs`、`warn_return_any`、`strict_optional`。只有 profile 已實測的鍵能啟用。
- 全域 `ignore_errors`、`ignore_missing_imports`，以及 `disable_error_code`／`enable_error_code` 的已建模有效 code 集合。
- strict 在 profile 具有完整展開表、且相關 overrides 已解析時，可以展開後比較；否則只做 declaration 事件。

### 10.3 規則

上述要求型旗標有效 true→false，且沒有其他有效設定補回同一要求時，產生 RULE_DISABLED。抑制型旗標 false→true 也以其具體移除的檢查維度報告，不能把所有 bool 的同一方向都當弱化。

`strict = true → false` 不直接構成 high：如果明確子旗標保留所有舊要求，應不報弱化；無法完整展開就 POLICY_CHANGED + INCOMPLETE。

`warn_unused_ignores` 等不在起始清單的旗標不偷渡成支援。`ignore_missing_imports` 的訊息限定為缺失匯入相關檢查，不宣稱所有型別檢查被關閉。

首版不解析 module override 與 inline precedence 的一般情況。分析涉及的來源含這些設定時，只將可證明不受影響的維度列為 complete；不能證明者為 incomplete。檔案存在但無法讀取，不算「沒有 inline 設定」。

### 10.4 regex 與 module 範圍

mypy exclude regex、files/packages/modules 切換、follow_imports 等變更，首版不產生 SCOPE_NARROWED 的強主張；輸出 POLICY_CHANGED 與受影響維度 incomplete。任意 regex 增長不等於匹配集合變大。

## 11 設定相容與正常變更

| 變更 | 要求 |
|---|---|
| 空白、註解、鍵排序 | 有效設定不變，不報弱化 |
| 集合型列表重排／重複項刪除 | 依工具語意正規化；順序有意義的區塊不得排序 |
| 同值跨檔搬移 | 只有兩邊來源解析與相依性閉包完整，才判等價 |
| 高優先設定新增 | 重新解析，不能只分析舊設定檔 |
| 新增整個工具設定 | 沒有 baseline 就不產生「降低」；若遮蔽舊來源則另論 |
| 整個設定刪除 | 檢查後備來源／缺省值；未知時 incomplete |
| 版本升級 | 不跨版本套用舊 rule catalog 或 strict 展開表 |
| 合法排除生成碼 | 仍可回報真實範圍變更，由人核准；不假設 generated 就天然安全 |
| 重構目錄或 rename | 無穩定對齊證據時只出宣告事件，不能猜是等價，也不能拿消失舊路徑證明縮水 |

## 12 豁免與政策變更

新增專用 `.checkwash/quality-allow.toml`，避免舊引擎對不認識的新指紋做不一致解讀。由 quality 讀取；現有 check 仍按 guardrail 規則處理 `.checkwash/**`。

每筆包含 `fingerprint`、`rule`、`target_id`、非空 `reason`、`author`、`created`、`expires`。到期與可重現日期遵循既有 base-side 豁免原則；期限上限建議沿用 180 天。author 是記錄欄位，不是身份驗證證據。

- 本 PR 在 head 新增的豁免只顯示為待審，不消除本 PR finding。
- base 已存在、未過期、內容精確相符的豁免才生效。
- 先以獨立 PR 審核豁免，再重跑原變更，是標準流程；不需要在同一 PR 內自我核准。
- 有效豁免保留 finding，標記 `allowlisted: true`，不計入 blocker。
- 禁止 wildcard、每 rule 全放行、只綁 path、只綁 before、縮短 digest。
- INCOMPLETE 與 engine error 不可豁免；不能用「接受風險」偽裝分析已完成。
- 豁免帳本本身的修改不得自行豁免；遵循既有維護者治理流程。

新增 quality 帳本的 append-only 新項目產生置頂審查事件，在 quality 自身不因單純新增而額外阻擋；修改／刪除現存項目為 critical。它們都不改變當次採用的 base 帳本。既有 check 對這個新檔案可能仍 critical，這是接線前必須由維護者決定的治理相容項，不能由 quality 暗中壓掉。

### 12.1 新指紋格式

`QW_RULE_ID/target-id/q1:<完整64位sha256>`。

三條可證明弱化的 high 規則，canonical JSON MUST 包含：rule、target id、事件類型、dimension、前後正規化值、所有相關來源路徑與 digest、discovery digest、profile id／digest；scope 事件另含受影響 witness 完整集合 digest。聲稱 high 卻缺少必要證據為 error，不退回舊式 fingerprint。

POLICY_CHANGED 審查事件、自身政策／帳本變更、discovery 事件與 INCOMPLETE 不提供 fingerprint。v0.4 quality 帳本只接受前三條 high 規則，避免宣告事件在證據不足時硬湊指紋。這些事件仍以明確來源與診斷呈現。

canonical JSON 使用 UTF-8、排序鍵、緊湊分隔、無時間與絕對路徑。集合先按規範排序。行號不入指紋。檔案 digest 保留註解與其他非換行 bytes，因此同一檔案後續修改可能使豁免失效；這是首版的保守選擇，文件必須直說。

重複相同內容與相同相依情境可跨 rebase 重用；同 path 的不同 after、不同 profile、不同 scope witness 都需要新審核。

## 13 資料模型與輸出

### 13.1 內部資料

`QualityTarget`：base 宣告、root、config、paths、profile。  
`SourceRecord`：snapshot side、repo path、digest、角色、有效／被遮蔽、選取原因。  
`ResolvedPolicy`：target、各維度 effective values、來源位置、完整性、unknown reasons。  
`PolicyDelta`：before／after、方向、losses、gains、witnesses、依賴證據。  
`QualityFinding`：rule、severity、證據層次、指紋、豁免與 remediation。

span 使用正規化文字的 character offset；輸出行列為 1-based。刪除鍵使用 before location；新增鍵使用 after；跨檔來源使用 related locations。不要用搜尋同文字第一個出現位置的方式猜 span。

### 13.2 JSON 摘要範例

以下為欄位示意，非可驗證 fixture；`<...>` 必須由實作替換。

```json
{
  "checkwash_quality_version": 1,
  "run": {
    "base": "<resolved-base>",
    "head": "<resolved-head-or-worktree-id>",
    "checkwash_version": "<candidate-version>",
    "mode": "enforce"
  },
  "analysis_status": "complete",
  "verdict": "block",
  "targets": [{
    "id": "coverage-main",
    "profile": "<qualified-profile-id>",
    "activation_evidence": "declared_only",
    "status": "complete",
    "checked_dimensions": ["coverage.report.fail_under"],
    "unsupported_dimensions": []
  }],
  "findings": [{
    "rule": "QW_THRESHOLD_LOWERED",
    "severity": "high",
    "target_id": "coverage-main",
    "evidence_level": "resolved_config",
    "dimension": "coverage.report.fail_under",
    "before": {"state": "known", "data": "85"},
    "after": {"state": "known", "data": "50"},
    "allowlisted": false,
    "fingerprint": "QW_THRESHOLD_LOWERED/coverage-main/q1:<64hex>"
  }],
  "diagnostics": [],
  "summary": {"blocking_findings": 1, "incomplete_targets": 0}
}
```

完整欄位以配套 JSON Schema 為準；本節只節錄重點，省略的 required 欄位必須由真實 producer 補齊。數值以 canonical decimal 字串呈現，禁止 NaN／Infinity。值不存在與解析未知分別表示，不用同一 null 混在一起。

summary.blocking_findings 指未豁免 high／critical 的數量，包括 report 模式下「如果 enforce 將阻擋」的 finding；實際退出仍由 mode 與完整性決定。incomplete_targets 包含 partial、unsupported、error targets；無 target 的 run error／discovery 由 run status 與 diagnostics 呈現，不能用此數字 0 暗示完整。diagnostics 是機器原因，INCOMPLETE finding 是其使用者呈現，統計不得算成兩個獨立弱化。

JSON 排序鍵、UTF-8、LF，無時間與耗時；相同輸入與 profile 得到 byte-identical 輸出。target 按 id；finding 按規則固定順序、target id、path、dimension、fingerprint 排序。

### 13.3 Terminal

```text
Checkwash quality · ENFORCE · BLOCK · analysis COMPLETE
HIGH QW_THRESHOLD_LOWERED [coverage-main]
pyproject.toml:18  coverage.report.fail_under  85 -> 50
Evidence: resolved configuration under the declared target.
CI execution was not verified.
Review the threshold change or record a content-bound exemption.
```

探索模式首行明確寫 `REPORT / DISCOVERY`。沒有已宣告 targets 時不能輸出「所有品質檢查通過」。

### 13.4 SARIF 與舊輸出

SARIF 使用 2.1.0 標準結構；quality 為獨立 tool component／run，rules 是新 ID，關聯來源用 relatedLocations，內容指紋放 partialFingerprints。severity 映射 critical/high→error、warn→warning、info→note。partial/error 用 toolExecutionNotifications 與 executionSuccessful 表達未完成，不能只省略結果。

舊 `checkwash check --format json` 保持 schema 2，不能混入 quality targets 或改變 verdict。新命令使用獨立 schema 1，兩者都不是對方的升級版。若未來合併命令，另提 schema 遷移，不在本版順手處理。

## 14 分析演算法與模組

```text
可信 base 政策 + base/head 快照
  → target 與候選設定 inventory
  → 各 adapter 解析來源及相依性
  → 各維度 effective values 與完整性
  → 語意差異與 source-backed witnesses
  → 規則事件與內容指紋
  → base 豁免
  → mode 對應 verdict／exit code
  → terminal / JSON / SARIF
```

建議新增 `src/checkwash/quality/`，包含 `model.py`、`policy.py`、`discovery.py`、`resolver.py`、`compare.py`、`fingerprint.py`、`verdict.py`、`profiles/`、`adapters/coverage.py`、`adapters/ruff.py`、`adapters/mypy.py`、`report.py`。

共用既有 Git snapshot reader 與安全文字輸出；不把 quality 專用欄位塞進 assertion strength lattice。adapter 輸出正規化資料，不直接決定是否阻擋；verdict 只讀結構化 enum，不解析英文訊息。

保留現有檔案 role；quality 用額外 capability 分析設定。`pyproject.toml` 可以同時承載 test runner 與品質設定，不因新功能被重新歸類為 production，也不能藉此新增 repair credit。

## 15 資源與惡意輸入

以下為提議硬上限，實作前凍結並測試，不是已量測效能：

| 資源 | 首版上限 | 超限 |
|---|---:|---|
| targets | 32 | 政策 error |
| 單設定來源 | 1 MiB | 受影響 target incomplete |
| 每 target 設定來源閉包 | 128 檔 | incomplete |
| 每次解析設定文字總量 | 16 MiB | incomplete |
| extend 深度 | 8 | incomplete |
| 一次路徑 inventory | 100,000 路徑 | scope 維度 incomplete |
| 每 target pattern 數 | 256 | scope 維度 incomplete |
| pattern 長度 | 1,024 字元 | scope 維度 incomplete |
| pattern × path 比較步數 | 1,000,000／target | scope 維度 incomplete |
| 報告顯示 witness | 前 20 個 | 全集 digest 與總數仍保留 |

不以 wall-clock timeout 決定可重現判決；以計數預算控制。程序被外部 timeout 終止不能當成 pass。TOML 使用 Decimal 解析非整數 token，INI 以嚴格 parser 與工具專用 section 名稱處理；拒絕重複衝突鍵與非有限數字。

symlink／submodule 不跟隨到 repo 外；相關來源無法安全取得即 incomplete 或 I/O error。路徑保持 Git 大小寫與 `/`；不依 OS case folding。拒絕 NUL、`..` 逃逸、絕對外部路徑。錯誤訊息不展開外部環境值。

不執行專案 plugin、配置 Python、任意 regex 或 shell。未知鍵若可影響所檢查維度，不得默認安全；確定與維度無關的 display／format 選項可按 profile allowlist 忽略，並保留來源證據。

## 16 Adapter 資格驗證

每個 profile 必須附精確工具版本、支援設定 schema、defaults、rule catalog／strict 展開表、來源優先規則、model digest、可信 qualification fixtures 與結果。模型資料隨套件離線分發。

資格驗證可在開發／測試環境執行固定版本工具，但只使用自己建立的可信微型 fixture，不執行任意外部 repository。這不改變交付核心的「不執行受分析專案」界線。

每個支援語意至少做前後差分對照：模型說等價，工具解析應一致；模型說某規則消失，建構違規 fixture 應呈現對應診斷差異。只比 adapter 的內部輸出不算 oracle。

profile 任何模型變更須重跑資格驗證並換 digest。現有豁免不能跨模型變更自動有效。選哪三個工具的首個精確版本，由 build 環境可重現性決定並填入交付清單；本文沒有虛構已通過的版本。

## 17 驗收案例矩陣

所有下列案例為必備種類，不代表只寫一例即足夠。新標籤由維護者審核；不得改舊 fixture 期待值來讓新功能過關。

| 編號 | 案例 | 期望 |
|---|---|---|
| C01 | coverage 85→50，條件相同 | THRESHOLD_LOWERED high |
| C02 | coverage 50→85 | 無弱化 |
| C03 | 85→85.0、重排／註解 | 無弱化 |
| C04 | 刪除 fail_under，已知有效 fallback 0 | high |
| C05 | 刪除來源，另一來源保持 85 | 無弱化 |
| C06 | 門檻變更同時改 precision／branch | changed + incomplete |
| C07 | omit 新增且移除仍存在的檔案 | SCOPE_NARROWED，列 witness |
| C08 | 排除 pattern 變化但沒有現存 witness | declaration，非 high scope |
| C09 | 未支援 regex／環境替換 | incomplete，不執行它 |
| R01 | Ruff 已啟用 code 加入有效 ignore | RULE_DISABLED |
| R02 | ignore 已經未啟用的 code | 無規則損失 |
| R03 | select 前綴與具體列表等價 | 無弱化 |
| R04 | 有 lost 與 gained rules | lost 保留 |
| R05 | 新 .ruff.toml 遮蔽 pyproject | 依真正來源結果判斷 |
| R06 | parent extend 變動，child 未改 | 偵測受影響 target |
| R07 | extend 循環／外部來源 | incomplete |
| R08 | 未支援 per-file ignore 已存在 | 受影響維度 incomplete |
| R09 | nested 設定改寫一個子目錄 | 只在該作用區域判斷 |
| M01 | disallow_untyped_defs true→false | RULE_DISABLED |
| M02 | ignore_errors false→true | RULE_DISABLED，具體說明 |
| M03 | strict 取消但全旗標補回 | 模型完整時無損失 |
| M04 | strict 無法完整展開 | changed + incomplete |
| M05 | error code 被 disable 但有效 enable 保留 | 不誤判，依 profile precedence |
| M06 | inline/module override 影響結果 | 不假設全域值就是最終值 |
| M07 | exclude regex 更長但不知包含關係 | changed + incomplete |
| T01 | head 把 mode enforce 改 report | 仍 enforce，critical policy finding |
| T02 | head 新增自我豁免 | 原 finding 不消失 |
| T03 | base 有合法精確豁免 | finding 保留、非 blocker |
| T04 | 同 path 不同 after | 舊豁免不命中 |
| T05 | profile digest 變化 | 不重用舊豁免 |
| T06 | source 解析錯誤與另一 finding 同時存在 | exit 2，兩者都呈現 |
| T07 | 未知 rule／版本 | 不用空集合通過 |
| T08 | 高優先新檔未追蹤且 worktree 可見 | 參與 discovery |
| T09 | 讀取中內容變動 | error，不混合兩次快照 |
| T10 | 正常移動、rename、CRLF、Unicode | 不因格式／平台產生不同語意 |
| T11 | 超限、symlink、repo 外 extend | 不崩潰、不越界、不靜默 pass |
| T12 | report 有 high | exit 0 但明確 reported |
| T13 | enforce 有 incomplete | exit 2 |
| T14 | 舊 check CLI 與 fixtures | verdict／fingerprint 不漂移 |

另需性質測試：格式等價保持、相同輸入決定性、加強無弱化 finding、head 政策不取得權威、不同 after 指紋不同、來源遮蔽可見、單一維度未知不抹掉其他已證明結果。

## 18 實際資料量測與發布門檻

既有測試弱化 corpus 的分數不能拿來當品質設定偵測率。新資料依 coverage／Ruff／mypy 分開，再依閾值／規則／範圍分層。

標籤至少有：`weakened_config`、`equivalent_or_strengthened`、`legitimate_weakening`、`unsupported`、`ambiguous`。其中 legitimate_weakening 是 weakened_config 的正當調整子類，統計時不得重複加進母數。

資料分為開發用與封存 held-out；同一 repo 的相鄰提交、同源 mutation 家族不可散落兩邊而假裝獨立。調參後用過的資料降為開發資料，不重掛 held-out 名稱。

### 18.1 建議預先登記的最低交付條件

1. 三個 adapter 的所有強制規格案例通過，0 個未解釋 verdict drift。
2. 每 adapter 至少 20 組已知支援弱化案例與 20 組正常對照；這是工程覆蓋，不是市場偵測率。
3. 新封存自然變更集合至少 90 筆、來自至少 6 個公開 repo，每工具至少 20 筆相關變更；來源、版本、選樣規則與 hash 先凍結。不足就如實記錄，不以人工 mutation 補自然資料母數。
4. held-out 中已宣告 complete 的正常等價／加強變更，不得有未解決的 high 誤報；有誤報就修正後換未使用資料重新評估，或延後 enforce 支援。
5. 若某 adapter 的自然樣本解析完成比例低於 70%，只能宣稱有限 preview，不列為已成熟的 enforce adapter。70% 是本提案的資格門檻，不是目前量測。
6. 舊核心固定回歸比較不能多出未核准行為變更。既有已知誤報可維持原紀錄，不能因本案順手重標。

零觀測誤報不等於真實誤報率為零。報告 MUST 帶母數、抽樣方式與不確定性；不把上述小樣本當通用品質保證。

### 18.2 必報指標

- 語意判定 precision：經審核確實降低設定要求的 high／已審核 high。
- 已支援弱化 recall：抓到的支援弱化／已標註支援弱化；另報所有弱化中 unknown／unsupported 比例。
- 完整解析率：complete targets／納入的相關 targets，另按 commit 報一次，避免混母數。
- 正常變更阻擋成本：等價／加強變更被 high 阻擋的比例。
- 操作成本：合法弱化所需豁免次數、review 時間、incomplete 導致的退出。
- 效能：固定硬體、固定 corpus 的 p50／p95 與峰值記憶體，放 benchmark artifact，不放 deterministic finding JSON。

## 19 實作工作包與依賴

估計為專注工程日的初步範圍，不是完成承諾；不含外部觀察等待。採單一路線逐包交付，無須新增 agent 或 repo。

| 工作包 | 內容 | 前置 | 交付驗收 | 粗估 |
|---|---|---|---|---:|
| P0 | 政策差異清單、最小 profiles 資格 fixture、schema 草稿 | 本提案 | 決策表與可信微型對照可重跑 | 1–2 日 |
| P1 | target／snapshot／resolver／limits | P0 | precedence、缺檔、未知與惡意輸入測試 | 2–4 日 |
| P2 | coverage threshold＋有限 scope | P1 | C01–C09 與真工具對照 | 2–3 日 |
| P3 | Ruff rules＋有限 scope | P1 | R01–R09 與真工具對照 | 3–5 日 |
| P4 | mypy 全域有限語意 | P1 | M01–M07 與真工具對照 | 2–4 日 |
| P5 | 指紋、豁免、verdict、三種輸出、CLI | P2–P4 | T01–T14、schema consumer 驗證 | 2–3 日 |
| P6 | 固定回歸、封存評估、文件、安裝與 CI 範例 | P5 | 發布門檻逐項有證據 | 3–5 日 |

合計約 15–26 個工程日。正式拆 PR 時，每輪仍維持一條規則或一個具名缺陷；工作包不是一次大 PR 的授權。

建議第一刀：**coverage 整數門檻下降**，但先建立來源解析與 unknown 路徑。完成後即可展示 `85 → 50`、`85 → 85.0`、同值搬移、未知覆寫四個反差清楚的 demo，再擴規則集合。

## 20 CI 接線、部署與回退

v0.4 初期仍讓現有 test check 與 quality check 分開執行、分開 status 名稱。quality report 模式先觀察；維護者在獨立政策變更中將 base mode 設為 enforce，並把 quality status 設為 required，才構成阻擋接線。

CI 文件必須說明：可信 runner／可信工具 pin、可信 base/head 選擇、無 continue-on-error、無條件執行、exit 2 不能視為通過，以及在線 branch rule 需另行確認。添加 workflow 本身不證明已阻擋 merge。

首次接入同時有「新 policy 不能在本 PR 生效」的 bootstrap 問題：安裝 PR 以 report 檢視並由維護者審核；合併後 base 有政策，下一個 PR 才進 enforce。不可讓安裝 PR 用自己的 head 政策授予自己保護聲明。

回退分兩種：工具回到已驗證固定版本，或由維護者獨立改 base policy 暫回 report。回退須保留觀察到的 failure／unknown 記錄；不改動原測量結果。舊版不認識新命令時要明顯失敗，CI 不得吞掉錯誤。

包裝延續單套件與離線分發方向；新增依賴只有經明確決策才採用。TOML／INI 與必要有限語法優先使用標準庫，避免為完整 YAML/shell 語意把首版範圍擴大。

## 21 與既有治理的差異

本文件是 workspace outputs 下的獨立提案，沒有修改 repository 的受保護檔案，也沒有發布、解除凍結或調低既有門檻。

[既有 AGENTS.md](https://github.com/taipei49314/checkwash/blob/387e71befedc387ab0c85af4c3322b7877a0cfd1/AGENTS.md) 將 SPEC、THREATMODEL、DECISIONS、tests/gates、severity policy 等列為維護者範圍。落地前需由維護者採納的具體差異如下：

| 決策 | 原因 | 提案預設 |
|---|---|---|
| 新命令與 quality schema | 新產品合約 | 獨立 schema 1，不改舊 schema 2 |
| 新 severity 與 incomplete 模式 | 影響何時阻擋 | report 預設；enforce unknown exit 2 |
| 新政策／豁免檔 | 與既有 guardrail 行為相交 | base-only，內容綁定，無自我豁免 |
| profile 和數值門檻 | 影響判定權威與升級 | 精確版本、固定 digest、測量後啟用 |
| 新 corpus labels／gates | 不能由實作者替自己改試卷 | 標籤審核與封存分離 |
| 恢復開發與未來發布 | STATE 記錄 refreeze，AGENTS 尚保留舊 release-slot 文字 | 先對齊治理紀錄，再安排發版 |

這些是實作接線前的具體採納項；本次已完成規格工作，不因待採納而省略設計。也不能因設計獨立 quality/verdict.py 就繞過原先對判決政策的維護者界線。

## 22 完成定義與後續方向

v0.4 完成意味著：三個有限 adapter、來源解析與未知狀態、模式與豁免、三種輸出、資格測試、獨立量測、CI 接線文件及回退方式都有可查驗產物；公開文案只寫已交付子集。程式存在、測試綠、套件可安裝，三者都不能單獨代替這份完成定義。

之後依真實 unsupported／誤報資料決定 v0.5：優先考慮更多設定語意、per-file／module overrides、CI 啟動條件與命令列覆寫。評測標準、證據 commit 綁定、production 安全檢查移除屬更後續主題，另立威脅模型與資料集，不把 v0.4 的數字延伸到那些領域。

本提案最重要的產品約束是：**每個警告都說清楚哪項要求變了、證據在哪，以及哪些事情還不知道。**

## 附錄 A 首版語法邊界與確定性

### A1 路徑語法

target.paths 是 Checkwash 自身的明確檔案／目錄清單；工具的 omit／exclude 則保留原工具語意，兩者不可混用。

首版工具 pattern 只接受：repo 內含 `/` 的 literal relative file path，以及 literal directory prefix 加 `/**`。literal segment 不得含 `* ? [ ] { } !`、反斜線、空 segment、`.` 或 `..`；尾端 `/**` 之外不可出現 wildcard。`src/private/**` 是候選支援形式，`**/private/*`、`*.py`、regex、brace expansion 首版視為未支援。工具內建 defaults 可由固定 profile 提供已驗證 matcher；不能把任意使用者 pattern 冒充 default。

上述是「輸入准入子集」，不是宣稱三個工具有相同匹配規則。每個 adapter 必須依其精確版本實測這些形式的 anchoring、相對目錄與後代匹配；若特定工具不支援某形式，該 profile MUST 不列入支援。不得用自行發明的 prefix 語意代替工具語意。對尚無共同支援證據的形式，接受 incomplete，不能為了提高解析率猜測。

scope 的證據宇宙 U 固定為 base/head 同路徑都存在、落在 base target.paths 內的 tracked 一般檔案。新檔案不提供「既有檢查損失」witness；未追蹤設定仍參與 worktree discovery。被刪除檔案與未對齊 rename 另列 declaration；不把它們當成 scope narrowing 證據。

### A2 每個維度的相依性

profile 為每個 dimension 列 `required_context_keys`、`harmless_keys`、`unsupported_interference_keys`。只有 required context 都已解析，且無可能影響該維度的未知值，才能 resolved_config。範例：Ruff output-format 不影響規則集合，可以忽略其值；per-file-ignores 可能影響實際區域要求，不能忽略。

沒有政策時的 discovery 只列設定宣告差異與候選工具，不自選版本 profile，不產生 high 或完整性保證。它的 analysis_status 為 partial，verdict 為 incomplete；即使完全沒發現候選設定，也寫明未建立 targets。格式仍合法、report exit 0。

### A3 原因碼

固定原因碼：`UNKNOWN_PROFILE`、`TOOL_VERSION_UNRESOLVED`、`UNSUPPORTED_KEY`、`UNSUPPORTED_PATTERN`、`DYNAMIC_VALUE`、`EXTERNAL_SOURCE`、`INHERITANCE_CYCLE`、`DISCOVERY_INCOMPLETE`、`CONTEXT_UNRESOLVED`、`RESOURCE_LIMIT`、`NO_BASE_TARGETS`、`POLICY_INVALID`、`SOURCE_INVALID`、`SOURCE_READ_FAILED`、`SNAPSHOT_CHANGED`、`INTERNAL_ERROR`。

從 UNKNOWN_PROFILE 到 NO_BASE_TARGETS 的 11 種為 incomplete 診斷；最後五種為 error。其中有效的來源刪除事件不屬 SOURCE_READ_FAILED：必須先區分 snapshot 中確實不存在與讀取失敗。

### A4 Target 狀態彙總

target 全部承諾維度已完成為 complete；部分維度完成為 partial；零維度完成且無硬錯誤為 unsupported；任何硬錯誤為 error。run 只要有 error 就 error；全體 complete 才 complete；全部 unsupported 則 unsupported；其餘為 partial。無 base targets 的 discovery 特例為 partial。

## 附錄 B Profile 交付格式與首批資格候選

profile 是隨 Checkwash 發布的唯讀資料，使用者只能選擇 ID，不可以從 head 提供新模型。其必要欄位為：`profile_schema_version`、`id`、`tool`、`tool_version`、`model_revision`、`digest`、`config_formats`、`discovery_precedence`、`supported_keys`、`defaults`、`dimension_dependencies`、`pattern_subset`、`qualification_receipt`；Ruff 另含 rule catalog，mypy 另含 strict expansion。

profile digest 計算排除 digest 本身與純說明文字，只包括所有會影響判斷的規範資料。qualification_receipt 指向套件內的固定測試資料與結果 digest；不能只是一個可變遠端 URL。report 同時輸出模型 ID 與 digest。

首批資格驗證候選固定為 coverage.py 7.16.0、Ruff 0.16.6、mypy 2.3.1，對應本次讀取的官方文件版本／Ruff 發行頁範例；它們是待驗證候選，沒有宣稱已在本環境測過。候選套件取得時還須驗證 package metadata 與 artifact hash；如無法重現取得，P0 記錄改選版本及理由，不暗換。

來源：[coverage 文件](https://coverage.readthedocs.io/en/latest/config.html)、[Ruff 發行頁](https://pypi.org/project/ruff/)、[mypy 文件](https://mypy.readthedocs.io/en/stable/config_file.html)。這些 latest/stable URL 會變動；實作必須在 qualification receipt 保存實際版本與取得內容 digest。

## 附錄 C 交付清單

- 本規格 Markdown：產品、語意、範圍、治理、測試與發版條件。
- 配套 `checkwash-quality-report.schema.json`：報告結構的提案 schema，可用來建立 consumer 與 fixture。
- 配套 `checkwash-quality-report.example.json`：已通過上述 schema 的合成結構範例。零值 digest 是明確佔位，不是引擎判決、有效豁免或 qualification receipt。
- 實作完成後應再產出：三個 qualified profiles、對照 fixtures、CLI／SARIF 樣本、固定回歸結果、封存評估紀錄、升級與回退說明。

schema 結構驗證不能代替語意驗收：例如有效 fingerprint 是否真的由來源計算、incomplete 是否採用正確退出碼、high 是否有充分證據，仍由本文件的跨欄位規則與測試約束。
