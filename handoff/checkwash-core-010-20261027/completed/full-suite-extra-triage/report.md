# 8a full-suite：六個額外失敗的只讀分流

Status: **READ_ONLY_TRIAGED / ACCEPTANCE_NONPASS / NO_PRODUCT_CHANGES**.

本報告只讀既有原生 JUnit/XML、stdout/stderr、固定 Git 與 fixture bytes，沒有重跑測試、import CheckWash、執行 fixture 程式，或改產品、gate、expected、allowlist。標記 **HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL**。來源是 **8a8941dc2d7c581715a0f6f196c00da6c55f084b**；收集前後 HEAD、clean tree 與本次 46 個 source/input hashes 均吻合封存 Git。

原 full-suite final/full-suite-311-r1/receipt.json 的 source/ending SHA 均為 8a，input manifest 為 3649879bd02d32a9e3d1f868790d7af33d86382300720b072bed0320ad14fe22，exit **1**。原生結果是 **22 failed / 21055 passed / 25 skipped / 67 subtests passed**。這六個指定失敗仍是失敗；本分流沒有把任何失敗改成 PASS。

## 六個失敗各自代表什麼

| 原生失敗 | 已觀察實際原因 | 分類與處置 |
|---|---|---|
| tests/test_packaging.py::test_readme_action_snippet_is_zizmor_blanket | 最後 trusted_version == max(prior) 比較得到 0.9.0 != 0.9.1。先前 README YAML、40-SHA pin、trusted tag peel、doctor allowlist 與 self-audit workflow parity 斷言均已走過。 | **發布測試契約假設不成立**：把本機存在的語義 tag 當作已驗證發布。需要使 freshness 判斷符合 verified advertised release；不能為變綠把 pin 改到未驗收 v0.9.1，也不能刪除必須保存的 tag。 |
| tests/test_state_claims.py::test_version_row_matches_package | STATE 權威表仍 v0.9.1，package 已為 v0.10.0。 | **機械文件 metadata 漂移**。未套用的最小修復是只把權威表 version 的 v0.9.1 同步為 v0.10.0；這不表示發布。若採納，必須產生新 revision 並依原要求驗證。 |
| tests/gates/test_refactor_corpus.py::test_no_silent_refactor_starts_blocking | CASE_020_windows、CASE_029_flatten 原 recorded PASS 現為 BLOCK，兩者 unique rule list 都只有 TEST_DISABLED。 | **兩個正常重構相容性成本**。要保留原 acceptance 修安全 proof，或逐案明確接受成本／更新記錄；不能自行改 protected expected。 |
| tests/gates/test_tamper_corpus.py::test_every_tamper_case_still_behaves | d007-factorial-of-zero、d010-stack-is-lifo 原 recorded authorized escape/PASS 現為 BLOCK，unique rule 都是 TEST_DISABLED。 | **兩個特定逃逸現在被攔截，但 frozen record gate 仍失敗**。需要逐案維護者記錄處置，不能自動宣告綠，更不能由此關閉整個 THREATMODEL 91/91a。 |
| tests/test_benchmark_snapshot_adapters.py::test_benchmark_wrappers_keep_frozen_corpus_verdicts_and_rule_parity[refactors] | 第一個 mismatch 是 CASE_020_windows: wrapper BLOCK、score BLOCK、want PASS。 | **舊 verdict 不符，沒有已證的 wrapper/score verdict 分歧**。同案後方 rule parity assertion 及後續案例皆未走到；不能聲稱整個 adapter parity 全通過。 |
| tests/test_benchmark_snapshot_adapters.py::test_benchmark_wrappers_keep_frozen_corpus_verdicts_and_rule_parity[tamper] | 第一個 mismatch 是 d007-factorial-of-zero: wrapper BLOCK、score BLOCK、want PASS。 | 同上；d010 的 gate verdict 已由另一個完整 gate 失敗訊息確認，但此 adapter test 未走到它。 |

這是六個 failing testcases、四個不同 corpus case identities，加上兩個 metadata/release-contract 問題；不要重複算成六個新的 corpus 缺陷。這些身份也不是 #567 八個 .gwcase 成本，或 candidate current-date selfdogfood 的兩個 issue266 high。

## 發布紀錄與文件契約

release/advertised.toml 明確把公開安裝身份與 development package 分開：verified public release 是 **v0.9.0 / d6eda4f695fabb8e7d138f7a87b099d2028f0294**。docs/RELEASING.md:1004–1020 說 Action recommendation 採 newest **verified** release，STATE 權威 version row 則是 development version。

本機 preserved tag 的只讀 peel：

- v0.9.0 → d6eda4f695fabb8e7d138f7a87b099d2028f0294
- v0.9.1 → 1ffe283d7d947fecc426dea99323b0a2620a9482

當 candidate 從 0.9.1 升為 0.10.0，已存在但未發布／未驗收的 v0.9.1 才落入測試「小於 current_version」的 prior 集合。這暴露原 test 的 tag-presence 假設；不是 README pin 不安全或 Action 實際執行失敗。測試名稱雖提 zizmor，此測試與本分流均沒有執行 zizmor。其「pin intentionally trails by one release」舊註解也不能取代較新的 verified-release 契約。

## 四個 corpus identities 與原始約束

原兩份 expected 均保留，且與 1ffe 完全相同：

- benchmarks/refactors/expected.json: SHA256 67cdda1ed2a3f3cef8d64b1e281041c12307e45ed2c169beb0077db47f240e42；60 案，56 案 recorded nonblocking。
- benchmarks/tamper/expected.json: SHA256 e25e32963dbacaba35130c484a1e5e5e85e91ed9a2bd979be9ca67582ad114ed；80 案，26 案 recorded PASS/authorized escape。

| identity | 原 expected | 已觀察新結果 | 只讀 fixture 含義與需決定的成本 |
|---|---|---|---|
| CASE_020_windows | blocks:false；rules:[TEST_DISABLED] | BLOCK；rules:[TEST_DISABLED] | 原兩個 direct tests 合為一個 test，兩次呼叫參數化同檔 helper，保留首／末 window 的 input/expected pairs。這是 helper／合併 context proof 的正常重構成本。原 row 已有同名 rule，不能只憑 unique rules 推論 severity、finding count 或其變化。 |
| CASE_029_flatten | blocks:false；rules:[] | BLOCK；rules:[TEST_DISABLED] | unittest TestCase 的 assertEqual methods 改為 top-level if-not-equal/raise AssertionError，保留具體 inputs/expectations。重構涉及 class identity／assertion dialect；此 gate 沒有記錄具體 credit 選擇，需精確評估成本，不用統一放寬代替。 |
| d007-factorial-of-zero | verdict:pass；threatmodel_row:91a；why: factorial of zero Mechanism: helper table omits failing input | BLOCK；rules:[TEST_DISABLED] | BEFORE 的 factorial(0)==1 在 AFTER table 中消失；table 只有 1、2、3、5 的正數案例。新增 assertion mass 不是原零輸入 obligation。新攔截與原 escape record 衝突，需逐案記錄處置。 |
| d010-stack-is-lifo | verdict:pass；threatmodel_row:91a；why: stack is LIFO Mechanism: base class not inherited by failing test class | BLOCK；rules:[TEST_DISABLED] | 原 push(1), push(2), pop()==2 改為 class test 的 pop()==1；新增 empty-pop 檢查是另一 obligation。原 why 原樣保留，本分流不重寫歷史描述或執行 Stack。 |

兩個 refactor 的完整原始 why 與所有原 expected 欄位完整保留於 triage.json，沒有裁切或改寫原 JSON。

表內 fixture 行為說明是**靜態讀取 source 的推論**。原 expected 的 provenance 記錄歷史 PROD-GOOD/PROD-BUG 或 before-red/after-green pytest qualification；本次未重做，不能把舊 provenance 冒稱成 8a 新 runtime qualification。

兩個 gates 本身已傳完整 HEAD 與 root snapshot callbacks（root_reader、root_searcher），因此沒有證據支持用「補個 strict root callback」消除這四個 mismatch。D-179 明確保留 unchanged corpus labels 的兼容性失敗，未授權自動豁免或改標。這五份 test sources、兩份 expected 在 1ffe→8a byte-identical；所有對應 hash 在 triage.json。

## 必須保留的驗收界線

- full suite **NONPASS**；備份／交接可以進行，不等於接受或發布。
- STATE 的機械 drift 可在後續明確 revision 修；目前 8a 不改。
- README freshness test 需對 verified-publication 契約做具體處置，保留 pin/security assertions、public090 pins、未發布091 tag 與暫停紀錄。
- refactor 兩案要安全 proof 修復或逐案接受成本；tamper 兩案要逐案記錄新增攔截。此報告沒有產生或套用 label patch，沒有 approval 推論。
- 本 gate 僅輸出 verdict 與 unique rule names，**未捕捉 full finding dict、fingerprint、severity**。本報告把它們記為 NOT_CAPTURED，沒有編造。
- 兩 adapter 首個 mismatch 後未達到的後續 parity 保留 NOT_REACHED。
- 本次結果不關閉整個 oracle 家族、THREATMODEL 91/91a、#567 八案、selfdogfood 兩 high 或其他未完成 qualification；1.0 前仍須停問。

## 保全與可核對檔案

- triage.json：原 full-suite receipt、原 raw streams/hash、46 個 source/fixture hashes 與 Git equivalence、原 expected、四 identity 分流、adapter observation bounds、只讀 Git 命令退出碼。
- selected-native-junit-failures.json：原 JUnit 六個完整 failure payload，另保留全體 failed testcase names、原 XML suite attributes、stdout 終態行。這是 derived extraction，原 XML 未改。
- collect_triage.py：僅 stdlib 讀 XML/JSON/source 和只讀 Git，輸出自己的 triage；不 import 產品、不執行 subjects、不跑 pytest。
- 收集命令：既有 work/test-runtime/Scripts/python.exe -I -B -X utf8 work/ux-stage4/full-suite-extra-triage/collect_triage.py，exit **0**；Python **3.11.9**、實際 host **LAPTOP-01AGNPJU**。此 exit0 只代表讀取與一致性 guard 通過，不代表產品測試通過。

Original raw receipts 保留在 work/ux-stage4/final/full-suite-311-r1/，本次未覆寫或搬移。沒有 modified judge、fixture label、gate 或 proposal 的執行結果。

