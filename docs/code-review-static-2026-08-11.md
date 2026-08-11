# greenwash 靜態 Code Review

> **範圍：** `src/greenwash/**`（v0.1.15 / HEAD）  
> **焦點：** 複雜度熱點、重複、邊界條件  
> **非焦點：** 威脅模型逃脫清單（見 `redteam-*.md` / `THREATMODEL.md`）  
> **方法：** 讀碼 + 結構度量；本機 `pytest` 全綠（Python 3.11）  
> **日期：** 2026-08-11  

---

## Summary

程式**健康**：零 runtime 依賴、管線清晰、測試全過、註解多數是「為何這樣寫」的威脅證據，不是裝飾。

主要工程風險不在「到處是 bug」，而在：

1. **三個上帝檔案**（`frontend` / `engine` / `gating`）承載幾乎全部語意，變更碰撞與回歸成本高。  
2. **刻意的字面/列表/一跳**邊界與紅隊洞重疊——靜態上可預期。  
3. **中等重複**（`_wraps`、glob match、AST dotted name）會讓修一邊漏另一邊。  
4. **少量 brittle 邊界**（用 finding message 字串分流、`unittest` 不填 name sets、collection 不掃 handlers）屬實作債，部分已在 THREATMODEL 掛號。

整體評級：**Alpha 級可維護的高紀律 codebase；維護性熱點集中，邊界債公開且可排程。**

---

## 1. 複雜度熱點

### 1.1 檔案規模（非空白行約數）

| 行數 | 檔案 | 角色 |
|------|------|------|
| ~1450 | `frontends/python/frontend.py` | AST → units / assertions / dead code / conftest |
| ~1105 | `engine.py` | FileChange → IR 全集裝 + CI/opaque/move |
| ~877 | `gating.py` | 全部 E/D 政策 + skip 條件求值 |
| ~386 | `cli.py` | 可接受 |
| ~233 | `ir/diffalign.py` | 對齊；相對清楚 |
| 其餘 detector | <200 | 小純函數，健康 |

**80% 風險與 80% 認知負荷在前三檔。**

### 1.2 上帝函式

| 函式 | 問題 |
|------|------|
| `engine.build_ir`（~440 行主體） | 單迴圈同時：角色/重分類、parse、align、globals、CI 弱化、opaque、import、move 前處理… 難單測「只改 opaque 規則」 |
| `gating.apply_gates`（~265 行） | 所有 oracle/非 oracle 升級路徑交織；補償、D2 spend、suite_control 疊在同一 for |
| `frontend` 內 `_extract_unit` / dead-code / classify 鏈 | 單一語言前端合理，但檔案已超「一人一次 PR 可安全改完」舒適區 |

**建議（不改行為的重構方向）：**

```
engine/
  build_ir.py      # 編排
  roles.py         # artifact / collectable / runner / inert
  ci_scan.py       # weakening / errexit / base surface
  evidence.py      # prod symbols / opaque / moved texts
gating/
  apply.py
  repair.py        # symbol/package/module reachability
  compat.py        # D6 eval + live
  compensations.py # rewrite / restructure / split
frontend/
  classify.py
  collect.py
  dead.py
  conftest_controls.py
```

重構必須有 **IR/json 對拍或全量 `.gwcase`** 當門禁（專案已有 determinism 文化）。

### 1.3 認知複雜度（非行數）

| 區域 | 為何難 |
|------|--------|
| Opaque 條件（engine ~776–826） | 多個否定交疊：pre-existing、非 self-inflicted、old_path 角色… 正確但難改 |
| D6 `_eval_condition` + `_discriminates` | 三值邏輯 + 常數閉包 + env matrix；正確性高、擴 helper 內聯風險大 |
| Assertion 對齊 fallback | 語意與 `ASSERT_SUBSTITUTED` 耦合；改對齊 = 改威脅面 |
| Repair evidence 多路徑 | symbol / one-hop caller / package / opaque / dep drift / suite_control 例外 |

這些**不應為了「好看」亂拆邏輯**；應拆**檔案邊界**，保持函式語意單一。

---

## 2. 重複（DRY 債）

### 2.1 高優先：行為重複，修一邊易漏

| 重複 | 位置 | 風險 |
|------|------|------|
| **`_wraps` 結構包含** | `assert_substituted.py` 與 `subject_normalized.py` **逐字重複** | 修 containment 邊界只改一處 → 規則不一致 |
| **glob / `**/` match** | `config._match` 與 `engine._scope_match` 同演算法 | scope 與 role 行為漂移 |
| **AST dotted name** | `frontend._dotted` 與 `gating._dotted_name` | 行為應相同；無共用 |
| **比較 op 表** | `frontend._CMP_OPS` 與 `gating._EVAL_CMP_OPS` | 靜態折叠 vs skip 求值；刻意分叉但易漏 op |

**建議：**  
`ir/astutil.py`：`dotted_name`、`expr_wraps`、`expr_equal`、`parse_expr`（markers 已有一部分）。  
`pathutil.py` 或 config 匯出：`match_glob(path, pattern)`。

### 2.2 中優先：結構重複（可接受但可抽）

| 模式 | 出現處 |
|------|--------|
| Detector 骨架：`for file if role in test/conftest` → units → pairs | 幾乎所有 oracle detector |
| `b_by_id` / `a_by_id` + pair 迴圈 | weakened / substituted / subject / expected_* |
| Finding 建構样板 | 各 detect |

可抽 `iter_assertion_pairs(ir) -> Iterator[...]` **僅當**不降低可讀性；現狀複製尚可接受。

### 2.3 低優先：字面列表分裂

CI swallow / narrowing tokens、runner suffixes、artifact segments 集中在 `engine.py` 是對的。  
問題是**列表本身是覆蓋模型**（紅隊已知），不是重複 bug。

---

## 3. 邊界條件與實作債

嚴重度：`bug`（行為錯或 silent wrong）/ `risk`（已知洞或 brittle）/ `maintainability` / `nit`。

---

### Issue 1 — Severity: risk  
**File:** `frontends/python/frontend.py` — `_local_bindings` / `_classify_unittest_call`  

**Description:**  
- `_local_bindings` 只認 `ast.Name` target → 解包、walrus、subscript 等不進 binding（THREATMODEL #86g）。  
- `_classify_unittest_call` **不填** `left_names` / `right_names` → `EXPECTED_VALUE_DERIVED` 在 unittest 上結構性死亡（#86b）。  

**Suggestion:**  
T1 引擎項：unittest 路徑與 bare assert 共用 name 抽取；bindings 擴 target 形。  
這是**覆蓋邊界**，不是隨機 typo。

---

### Issue 2 — Severity: risk  
**File:** `frontends/python/frontend.py` — `_collection_controls`  

**Description:**  
`record` 走 `body`/`orelse`/`finalbody` 與 `_STMT_BODY_FIELDS`，**不處理 `handlers`**；target 只接受 `ast.Name`。  
→ `except ImportError: collect_ignore.append(...)` 與 `collect_ignore[:] = [...]` 漏（#83）。  

**Suggestion:**  
與 dead-code scan 對齊：handlers 也 `record`；slice/下標 target 納入 control()。  
需 pos fixture 防回歸。

---

### Issue 3 — Severity: risk  
**File:** `gating.py` — `_prod_removal_shape`  

**Description:**  
用 **finding message 子字串** `"disabling marker added" not in f.message` 區分 TEST_DISABLED 形狀。  

```python
and "disabling marker added" not in f.message
```

message 一改文案，補償邏輯靜默錯。  

**Suggestion:**  
`Finding` 加 `kind` / `shape` 枚舉（或 structured code），detector 寫入，gating 不 parse 英文。

---

### Issue 4 — Severity: risk  
**File:** `detectors/assert_weakened.py` vs `assert_substituted.py`  

**Description:**  
- weakened：`subject_changed` 用 **`normalize_text` 字串**  
- substituted：subject 用 **`ast.dump` 結構**  

同一語意「subject 是否變」兩套定義 → reformat / 等價寫法邊界不一致（與 #86f 同源）。  

**Suggestion:**  
共用 `ir/astutil.same_expr` / `subject_equal`；weakened 的 mild 判斷也走結構。

---

### Issue 5 — Severity: maintainability  
**File:** `engine.py` — `build_ir`  

**Description:**  
單函式編排過多階段；opaque / CI / move credits 交錯。  
未來「只改 opaque」PR 易誤傷 move 或 CI。  

**Suggestion:**  
按 §1.2 拆模組，**行為零 diff**（IR JSON 對拍）。

---

### Issue 6 — Severity: maintainability  
**File:** `gating.py` — `apply_gates`  

**Description:**  
補償順序、D2 multiset spend、suite_control、dep_drift 全在一處。  
正確性靠註解與 corpus，新人難證「只動 D8 不影響 D2」。  

**Suggestion:**  
拆 `_apply_oracle_gate(f, ctx)` / `_apply_non_oracle(f, ctx)`；ctx 持有 moved counters。

---

### Issue 7 — Severity: maintainability  
**File:** `detectors/assert_substituted.py` + `subject_normalized.py`  

**Description:**  
`_wraps` 重複（§2.1）。  

**Suggestion:**  
單一 `expr_structurally_wraps(before, after)`。

---

### Issue 8 — Severity: nit / risk  
**File:** `gating.py` — `RULE_ORDER`  

**Description:**  
缺 `TEST_FILE_UNPARSEABLE`、`CONFTEST_PATCHES_PROD`（及可能 `EXEMPTION` 以外新 rule）。  
`Finding.sort_key` 對未知 rule 用 `len(RULE_ORDER)` → **排序不穩定於「嚴重性敘事」**，不影響 verdict，影響 report 穩定性（若有人依賴 order）。  

**Suggestion:**  
REGISTRY 與 RULE_ORDER 由單一表生成，或 test 斷言「registry ⊆ order」。

---

### Issue 9 — Severity: risk（已知產品邊界，靜態可見）  
**File:** `engine.py` — runner / CI tokens  

**Description:**  
`_runner_shape` basename/suffix/shebang 枚舉；swallow/narrowing token 列表。  
靜態上可預期 #75–77 類漏與間接 script 漏。  

**Suggestion:**  
T1.5 one-hop + 擴 shape；長期避免無限加字串。

---

### Issue 10 — Severity: risk（已知）  
**File:** `gating.py` — `_module_reachable` + `engine._module_of`  

**Description:**  
`_module_of` strip `src/`；import 側帶 `src.` 時 evidence 可能失敗（#86h FP）。  
靜態可讀出不對稱。  

**Suggestion:**  
import 側也 strip 已知 source root，或雙向 suffix。

---

### Issue 11 — Severity: nit  
**File:** `gating.py` — `_is_real_assertion(a)`  

**Description:**  
參數無型別；magic `60`（PATTERN）與 strength 模組常數未命名引用。  

**Suggestion:**  
`from greenwash.ir.strength import PATTERN`；`a: Assertion`。

---

### Issue 12 — Severity: nit  
**File:** 多處  

**Description:**  
註解極長（有價值），但 `apply_gates` / opaque 區塊 **註解:code 比** 高，diff review 疲勞。  

**Suggestion:**  
長故事進 DECISIONS/THREATMODEL，碼旁留「row N + 一句」。

---

### Issue 13 — Severity: risk（邊界）  
**File:** `ir/diffalign.py` — order fallback  

**Description:**  
Fallback 配對是正確的工程選擇，但 **所有「strength 未降的替換」** 都依賴後續 detector 擦屁股。  
靜態上：alignment 模組與 `ASSERT_SUBSTITUTED` **契約未型別化**（僅 `fallback: bool`）。  

**Suggestion:**  
考慮 `pair_reason: literal | subject | order` 枚舉；測試對齊「僅 order 才進 SUBSTITUTED」。

---

### Issue 14 — Severity: bug?（需確認，低可能）  
**File:** `engine.py` — `resolvable` 建構  

**Description:**  
```python
for part in change.path.split("/"):
    resolvable.add(part[:-3] if part.endswith(".py") else part)
```  
路徑段 `tests`、檔名 stem 都進 resolvable → **IMPORT_UNRESOLVED 偏鬆**（假 resolved）。  
若為故意 generous（deps.py 註解 false resolved 成本），應在碼註標明；否則 third-party 漏報。  

**Suggestion:**  
對照 SPEC / deps 意圖；加負例「新 import 純幻覺且 manifest 無」。

---

## 4. 什麼做得好（review 必須寫）

| 優點 | 說明 |
|------|------|
| 管線邊界清晰 | FileChange → IR → detect → gate；fixture 同路徑 |
| 決定性紀律 | 排序、Counter multiset、不用 set 迭代進輸出 |
| 失敗導向註解 | 多數長註解對應 bypass 列，可審計 |
| Detector 小而純 | registry 顯式，無動態載入 |
| 測試文化 | `.gwcase` + pin + threatmodel 閘 |
| Base-side config | 攻擊面在設計層收斂 |
| 本機全測綠 | 靜態債 ≠ 紅燈債 |

---

## 5. 優先修復建議（工程，非紅隊全表）

| 優先 | 項 | 類型 | 預估 |
|------|-----|------|------|
| P0 | 抽 `_wraps` / `same_expr` 到 `ir/astutil` | 重複 | 小 |
| P0 | Finding shape 取代 message 子字串（Issue 3） | brittle | 小–中 |
| P1 | RULE_ORDER ↔ REGISTRY 一致性測試 | nit→門禁 | 小 |
| P1 | unittest 填 name sets；bindings 擴 target | 覆蓋 | 中 |
| P1 | collection_controls + handlers/slice | 覆蓋 | 中 |
| P2 | `build_ir` / `apply_gates` 拆檔（零行為 diff） | 維護 | 大 |
| P2 | weakened subject 改結構比較 | 一致 | 小 |
| P2 | `_module_of` / import 對稱（#86h） | FP | 小 |
| P3 | 註解遷 DECISIONS，碼旁縮短 | 可讀 | 持續 |

與產品路線圖對齊：P1 覆蓋項 ≈ `ROADMAP-top-tier.md` T1；拆檔屬工程衛生，可與功能 PR 分開。

---

## 6. 複雜度熱點圖（心智模型）

```
                    cli / cases / gitio
                            │
                            ▼
              ┌─────────────────────────┐
              │  engine.build_ir        │  ← 熱點：編排+政策副作用
              │  (+ roles, CI, opaque)  │
              └───────────┬─────────────┘
                          │ IR
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
   frontend.py      diffalign.py    DiffGlobals
   (最大檔)          (清晰)         (欄位膨脹中)
          │               │
          └───────┬───────┘
                  ▼
            detectors/*     ← 健康、小
                  │
                  ▼
            gating.apply    ← 熱點：全部 E/D
                  │
                  ▼
              report / verdict
```

**DiffGlobals 欄位持續增加** 是第二熱點：新全域信號 = engine 填 + detector 讀 + gating 可能讀。  
長期可考慮「typed side-channels」或分 `OracleGlobals` / `CiGlobals`，避免單 dataclass 無限長。

---

## 7. 結論

| 問題 | 答案 |
|------|------|
| 程式寫壞了嗎？ | **沒有。** 測試綠、結構有意識、失敗公開。 |
| 有靜態問題嗎？ | **有：集中複雜度、幾處 DRY、若干 brittle/覆蓋邊界。** |
| 會不會明天炸？ | 低；炸點多在**改三巨頭時的回歸**，不是隨機 NPE。 |
| 最該先做的工程事？ | 共用 astutil；Finding 結構化 shape；REGISTRY/ORDER 測試；再談拆 `build_ir`。 |

**一句話：**  
這是 **高紀律、高集中度** 的 codebase——問題在「**難改對的地方太集中**」和「**邊界與威脅模型同構的債**」，不是「到處是低級錯誤」。

---

## 附錄 — 與其他文件

| 文件 | 關係 |
|------|------|
| [ROADMAP-top-tier.md](./ROADMAP-top-tier.md) | 產品/逃脫優先；本檔是**碼內工程**優先 |
| [redteam-weaknesses.md](./redteam-weaknesses.md) | 攻擊面；本檔 Issue 1–2/9–10 對應 |
| `THREATMODEL.md` | 權威 bypass 表 |
| 本檔 | 維護性 + 實作 brittle |
