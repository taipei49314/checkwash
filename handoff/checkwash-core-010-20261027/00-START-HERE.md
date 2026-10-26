# CheckWash 0.10.0 候選交接

備份時間（UTC）：2026-10-26T19:23:07.177873+00:00。這份資料保存工作進度，不代表產品驗收或發布。
程式固定為 `8a8941dc2d7c581715a0f6f196c00da6c55f084b`，分支 `fix/ux-repairs-20261026`；[PR #566](https://github.com/taipei49314/checkwash/pull/566) 維持 draft。
[最新遠端入口](https://github.com/taipei49314/checkwash/blob/handoff/core-010-pju-20261027-8a8941dc/handoff/checkwash-core-010-20261027/00-START-HERE.md) 會隨 checkpoint 更新。測試的程式 SHA 是 8a8941dc，交接分支上的備份 commit 不冒稱測試來源。

來源、installed wheel、pyz 各 283/283 資格案例通過；raw offset／hash、suite／package 身分與 wheel／pyz 各 212 package members 已回讀核對。
同一台 Windows 主機的 Python 3.11.9／3.12.14，1,117 個 fixture 的完整 findings+IR 共 8,873,976 bytes 完全相同。
Python 3.12 的指定 104 tests 通過。原 36 次 native CLI 觀察為 24 BLOCK／12 PASS，包含 26 個明列斷言與 10 個觀察列，不能說成 36 個已裁決的測試。
完整回歸仍在執行；21,102 是已收集的 parent tests 數，尚不是通過數。

候選版對自己 PR 的檢查仍是 **BLOCK／exit 1：2 high、8 warn**，無 config error／skipped file；這兩個 high 是 D179 普通 consumer test 遷移改名，詳見 [對照](completed/selfdogfood-issue266-review.md)。
公開 v0.9.0 Action 的 PJU 本機重播同範圍 exit 0；它的結果不會清除新候選版的 BLOCK。這些本機收據沒有發布 formal release check-run，也沒有驗收跨作業系統或 Python 3.13。

[#567](https://github.com/taipei49314/checkwash/issues/567) 的 8 個既有 golden 預期仍未修改、未核可。expected-only patch 是未套用提案；禁止把它當已批准的裁判或 PASS。
產品不趕發版。未 merge、新 tag、Release、PyPI 或 downstream re-pin；**在 1.0 前停下請 Nelson 決定**。

## 保存的資料

目前已有程式遠端分支、資格摘要與三次歷史 sanitized 證據包；完整回歸的 raw 收據與本次完整包待執行結束後補上。

- [legacy-stage1-sanitized.zip](legacy-stage1-sanitized.zip) — 11009496 bytes；SHA256 見同名 `.sha256`。
- [legacy-stage2-sanitized.zip](legacy-stage2-sanitized.zip) — 14057012 bytes；SHA256 見同名 `.sha256`。
- [legacy-stage3-sanitized.zip](legacy-stage3-sanitized.zip) — 11513483 bytes；SHA256 見同名 `.sha256`。

三個 legacy 新包保留 task-only 檔案，移除 global memory 原文與內嵌原 ZIP。原 ZIP 在本機保持原 bytes，不能直接公開上傳。
新包有自己的 manifest／排除紀錄；保留的舊 manifest 只是歷史 inventory，不能當新包完整 manifest。
本資料夾真正入口是 `00-START-HERE.md` 與 `checkpoint.json`；legacy 包中若提及 START-HERE/status，請讀這兩檔。
交接分支的 `partial-qualification/` 與 `resume-tools/` 是第一個 checkpoint 的歷史快照，最新狀態以本入口／checkpoint.json 為準；不要直接在該平鋪位置跑相對路徑腳本。

## 換環境後接續

將本次 core ZIP 解到新的 task workspace 根目錄，保留 `work/ux-stage4`、`work/trusted` 和選定外部依賴的原路徑；詳細 mapping 見包內 RESTORE-MAP.md。
在 `work/checkwash-ux` 準備乾淨 Git checkout，取得並固定 `8a8941dc2d7c581715a0f6f196c00da6c55f084b` 與 baseline `1ffe283d7d947fecc426dea99323b0a2620a9482` 兩個 Git objects。
source ZIP 保存 byte 身分，單獨解壓不會提供 qualifier 所需的 Git history。依 runtime／dependency 收據重建隔離環境，核對 interpreter 的實際絕對路徑後才跑腳本。
讀產品 STATE.md、AGENTS.md、docs/repair-integration-0.10.0.md 與現行主機政策。PJU 可直接依有效授權執行；不重新調查已要求停止調查的 pool 斷網，也不復活 consumed／paid-model 批次。
歷史收據保留實際主機 LAPTOP-01AGNPJU 與 HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL；複製資料不等於另一台主機的新驗證。保留所有失敗與 partial 原件。
