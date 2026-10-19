## Material Passport

- Origin Skill: ARS `experiment-agent`
- Origin Mode: validate（凍結紀錄的唯讀個案審計）
- Origin Date: 2026-10-19，Asia/Shanghai
- Verification Status: ANALYZED；核對既存雜湊、重新計算選擇與事件清單，未重新生成或重跑隱藏評測
- Version Label: e0-case-audit-v1
- Repro Lock: null；來源凍結雜湊與重播憑證另存於 run artifacts，沒有獨立重跑自然生成。
- Stage: E0 工程探索；本文件不構成 E1 證據
- Evidence Type: natural_local_generation；固定 Qwen/Qwen2.5-Coder-7B-Instruct revision `c03e6d358207e414f1eca0bb1891e29f1db0e242`
- Review Provenance: 同一 Codex 協作會話中的子代理，繼承既有上下文；不是盲審、跨模型獨立審查或供應商認證
- Writable Scope: 僅本文件；未修改配置、程式、候選、生成測試、矩陣、選擇或標籤，未啟動 GPU、重新生成或外部 API

## 範圍與主要發現

對 E0 全部 20 題、五個選擇器重新枚舉 `perturbed` 相對 `top2` 的 gain/loss，以及「原選擇錯誤，但完整通過行相同的候選中有正確程式」事件。先按選擇器枚舉，再按 task ID 去重審讀，完整範圍只有 **Mbpp/294 與 Mbpp/446**，沒有 loss 題。

| Selector | Gain task IDs | Loss task IDs | Identical-row blind-spot task IDs |
|---|---|---|---|
| uniform | 無 | 無 | Mbpp/446 |
| aces_c | 無 | 無 | Mbpp/446 |
| dedup_uniform | Mbpp/294 | 無 | Mbpp/446 |
| group_equal | 無 | 無 | Mbpp/446 |
| group_rep | 無 | 無 | Mbpp/446 |

這是同一批資料上五次讀取的事件，不能把 Mbpp/446 當成五道獨立題。`dedup_uniform` 的候選覆蓋由 15/20 變成 16/20；其他四個選擇器均維持 15/20。候選集合覆蓋是集合內存在正確程式的上限，本次沒有執行 E2 審核。

- **Mbpp/294：有真實的集合覆蓋增加，但沒有真來源分組優於隨機分組的證據。** 刪掉一組後唯一的行為列模式消失，錯誤程式與正確程式同分，固定 hash 次序使正確程式成為一次刪組贏家。全部 20 個預定隨機分組亦選出相同集合和 7:1 票數。
- **Mbpp/446：有完整矩陣盲區。** 十四個程式的 64 位通過行完全相同，其中十二個錯誤、兩個正確。唯一能使兩類程式輸出不同的生成測試，其期望值使兩類都失敗，二元矩陣抹掉了差異。
- 兩題關鍵候選的差異可由型別過濾、重複計數和生成測試期望值解釋。紀錄中沒有 timeout、依賴缺失或資源耗盡造成這兩個事件的證據。這兩題另有五個候選因程式碼區塊內獨立一行 `python` 而立即 `NameError`，應單列為格式／執行錯誤，不能當成自然解題邏輯錯誤或可見／隱藏環境差異；完整 E0 的同類格式殘留候選數為 36，另見 execution-audit.json。

## 檔案、來源與核對方式

原始證據需從 [e0-e1-v1 發布附件](https://github.com/Freezingc/test-group-selection/releases/tag/e0-e1-v1) 還原後讀取：`artifacts/runs/e0-v1/raw/` 中的 tasks.jsonl、selections.jsonl、generation.jsonl，以及 `artifacts/runs/e0-v1/evaluation/` 中的 labels.json、samples_eval_results.json。官方標籤定義為 EvalPlus 0.3.1 的 base、plus 兩者皆 pass；`fast_check` 在首個失敗停止，因此失敗紀錄的 details 長度不是該 suite 的總測試數。

核對步驟：

1. 以 `validate_frozen_inputs` 檢查 E0 完整 20 題、同一 split、matrix/selection/config 的完成 manifest 與目前位元組雜湊。
2. 對照 `inputs.manifest.json` 的四份輸入雜湊與 evaluation receipt 雜湊；核對 matrix manifest 中的 generation 雜湊及 evaluation receipt 的隱藏結果雜湊，均相符；receipt 為 completed。重新以 `read_evaluation` 解析官方結果與 candidate index，得到的全部標籤與凍結 labels 逐鍵相等；目前官方完整快照的位元組雜湊亦符合固定值。
3. 從所有 20 題重算五選擇器的 gain/loss/盲區清單。對兩個入選題，重新執行五個純矩陣選擇器，輸出與凍結紀錄逐欄完全相等，包含刪組排名與票數。
4. 審讀兩題所有 32 份候選及全部 128 條生成測試、完整 16×64 矩陣和可見執行例外；審讀既存官方 base/plus 狀態。僅在凍結後的本次離線個案解釋中查看兩題官方輸入及參考函式；未將其送回生成、測試過濾或選擇。
5. 對 Mbpp/446 使用字面值解析和兩個明確計數公式，重算全部 64 條斷言的真值，與 candidate/07、candidate/09 的矩陣逐位相同；沒有直接執行不受信任的候選原始碼。

| Artifact | SHA-256 |
|---|---|
| frozen config | `ff38b4d4676c37cf4066e425c7f276aa3d2bc4e219f6cfb3ccedd1c8f141f9b7` |
| generation.jsonl | `48532e4df9b8deec112418a8afa3a3b1e450d14ca12b3daa7a7a7a5995583167` |
| tasks.jsonl | `bad83068bef7698dedd53bd23debf422cf90b1111d7bd850012bdf43bde62fa3` |
| selections.jsonl | `0ca87919a6fc967df80fb84d869f1fd32b66588007eacc4515213039f9dd3cb6` |
| labels.json | `56ddb82a9bf9e170da74ba7ab4e12b3523a2b611f7c03296f6a2018132749c12` |
| samples_eval_results.json | `08cd6e6302c14b27dd14e634b3e1d230da8e5b0a7d01cfaeedf13ae46cfb72cb` |
| official full snapshot | `b54e762755248ca411b523c917fa9f93c07b5ff2966bf60b3917b853926a3dad` |

本次的「重算」限於事件枚舉、選擇和已解析字面值的確定性算術；沒有重新生成候選／測試，也沒有重跑官方評測。因此 passport 保持 ANALYZED。

## 個案一：Mbpp/294，最大整數與泛型最大值混淆

### 已核實的選擇和標籤

公開範例為 `max_val(['Python', 3, 2, 4, 5, 'version']) == 5`。固定官方參考在 `isinstance(i, int)` 過濾後求最大值；Python 的 bool 亦符合此判斷。本題共有 16 份可解析且來源互異的候選，8 組各 8 個測試，無測試解析失敗。

下文 `cXX` 為 `Mbpp/294/candidate/XX`，`gXX` 為 `Mbpp/294/tests/XX`。

| Candidate | 核心行為 | Visible pass/64 | Official base | Official plus | Label |
|---|---|---:|---|---|---:|
| c00 | 整數過濾，無整數時回傳 None | 36 | pass，3/3 | pass，108/108 | 1 |
| c05 | 從首元素開始，不過濾型別而使用 `>` | 48 | fail，details `[0]` | fail，details `[0]` | 0 |
| c14 | 首元素初始化，之後僅檢查整數，仍可能和字串／None 比較 | 32 | fail，details `[0]` | fail，details `[1,0]` | 0 |
| c08 | 過濾 int 或 float，初值為負無窮 | 37 | pass，3/3 | fail，第 98 個執行到的 case | 0 |

`dedup_uniform` 的原始前五名為 c05、c14、c00、c08、c02；原始分數分別為 4、3、3、3、3。所以 Top-2=`[c05,c14]` 的 coverage=0，perturbed=`[c05,c00]` 的 coverage=1。c00 並非來源別名聚合的產物：16 份 source hash 均不同。

### 刪組如何產生唯一增益

完整矩陣只有七種不同的 16 位列模式；`dedup_uniform` 對每種模式計一票，其中一種為全零列，不影響候選得分。全矩陣下 c05 得 4 分，c00 得 3 分。

| 刪除來源組 | 刪組 winner | Source vote |
|---|---|---:|
| g00、g01、g02、g03、g04、g06、g07 | c05 | 7 |
| g05 | c00 | 1 |

g05 的第六條、全矩陣 index 45，是：

```python
assert max_val(['z', 'y', 'x', 'w', 'v']) == 'z'
```

它在 16 份候選上的通過列為 `0000110100000010`，即只讓 c04、c05、c07、c14 通過。這個列模式全矩陣僅出現一次。刪 g05 後，其他六種模式仍存在，但此模式消失；c05 分數降至 3，c00 保持 3，c14 降至 2。此時 **c00、c05、c08、c02 同為 3 分**，固定 `SHA256('tgselect-v1:'+task_id+':'+candidate_id)` 平局次序選中 c00。這是「分數差縮到平局，再由預先固定次序選中正確程式」，不能描述為正確程式在分數上嚴格超越所有錯誤程式。

選出的擾動集合保留原 c05，再加入唯一非原 source 贏家 c00；Raw W 亦為 `[c05,c00]`。均勻、ACES-C、每組等權在八次真刪組中均由 c05 勝出。group_rep 由 c05 得 6 票、c14 得 2 票，未增加正確候選覆蓋。

### 生成測試的偏差與例外

64 條生成測試中 **29 條完全沒有 `isinstance(x,int)` 的元素**，包含空串列、純字串、純浮點、巢狀串列與字典。官方參考對這些輸入的過濾集合為空，並不回傳測試聲稱的泛型最大值或 None。不能把這 29 條全部稱為「已證實語義非法」；公開文字對域的規格不完整，但它們超出本題官方參考可回傳數值的輸入域，且與固定隱藏判定不一致。

另有四條輸入確實含整數、期望值仍與固定參考不符：

| Index / test ID suffix | Input | Generated expected | 固定參考值 |
|---|---|---|---|
| 5 / g00/t05 | `[None,0,'0',False]` | `'0'` | `0` |
| 6 / g00/t06 | `[1,2,3,'a','b','c']` | `'c'` | `3` |
| 11 / g01/t03 | `[None,0,-1,-2]` | `None` | `0` |
| 30 / g03/t06 | `['a',1,2.5,'z',3]` | `'z'` | `3` |

這些列均依原協議保留，本審計沒有事後按參考答案移除測試。泛型最大值 c05 在 22 條沒有整數的測試中恰好符合生成期望，因而在可見矩陣達 48/64；整數過濾 c00 僅 36/64。兩者共同通過 26 條，僅 c05 通過 22 條，僅 c00 通過 10 條，兩者都不通過 6 條。c00 對五個空串列回傳 None，也得到官方參考不定義之域外測試的額外可見分數；不能把 c00 的每一個通過都視為可靠 oracle 證據。

c05 在公開範例必然嘗試比較整數和字串；c14 亦會從首字串初始化而進行相同比較。可見紀錄分別包含 16 和 8 個 `TypeError/IndexError` 類程式例外，並與兩者 official base fail 相容。隱藏結果只保存 pass/fail/details，沒有逐 case 的例外 traceback；本文件對其具體失敗原因的說明來自程式靜態語義，而不是聲稱看到隱藏 traceback。c08 的 plus 首個失敗對應 index 97 輸入 `['3.14',False,7.5]`；它會選 7.5，固定整數參考選 False（與 0 數值相等），可由數值型別域差異解釋。

### 隨機分組反解釋

本題 `dedup_uniform__random_0` 至 `__random_19` **全部**回傳 `[c05,c00]`，票數均為 c05:7、c00:1。原始 scorer、原始 c0 與 Top-2 在隨機對照下固定。故本題雖對 Top-2 增加 coverage，真來源分組對 20-seed 隨機平均的增量為 **0**。這個個案支持「一次刪組能移除稀有列模式、暴露平局中的另一候選」的機械解釋，不能支持來源群組語義、因果依賴或來源結構帶來額外優勢。

## 個案二：Mbpp/446，重複查詢元素與完整矩陣盲區

### 已核實的選擇和標籤

本題要對查詢串列中的每個元素累加其在 tuple 中的出現次數。固定參考為 `sum(tup.count(ele) for ele in lst)`，保留查詢串列的重複次數。下文 `cXX` 為 `Mbpp/446/candidate/XX`。

十四個非格式錯誤候選中：

- c01、c03–c08、c11–c15 共十二個採用「遍歷 tuple，若元素屬於查詢 list 就加一」，等價於 `sum(x in lst for x in tup)`，忽略查詢 list 的重複次數。
- c09、c10 按查詢 list 的每一項累加 tuple 頻數；兩者 base 3/3、plus 104/104，label=1。
- 十二個 membership 候選皆 base 3/3，但 plus details 為 `[1,0]`，label=0。第二個 plus case 的 tuple 有 1、2、3 各三次，查詢 list 為 `[1,1,2,2,3,3]`：membership 計 9，固定參考及 c09/c10 計 18。

上述十四個候選的完整行完全相同，均為 50 pass、14 assertion_fail、0 program_error。另兩份 c00、c02 因格式殘留 `python` 形成全零行。因此本題 16×64 矩陣只有兩種行，也只有「十四個成功執行候選皆通過」和「全零」兩種列。

五個選擇器的原始 winner 皆 c07，Top-2 與 perturbed 皆 `[c07,c13]`，二者 coverage 都為 0。c10 原始順位第 7，c09 第 11，皆被固定平局次序排在 Top-2 外。五選擇器的八次刪組 **全部仍由 c07 勝出，票數 8:0**，Raw W 只有 c07。固定平局規則正確阻止了同一行因重新隨機平局而虛構替代 winner。

| Selector | 十四個共同非零行的得分 | c00/c02 得分 |
|---|---:|---:|
| uniform | 50 | 0 |
| aces_c（等價整數尺度） | 1400 | 0 |
| dedup_uniform | 1 | 0 |
| group_equal | 6.25 | 0 |
| group_rep | 5 | 0 |

### 唯一具區分性輸入被錯誤期望掩蓋

64 條生成測試中，只有全矩陣 index 46 的兩類計數公式會回傳不同值：

```python
assert count_Occurrence(('a','b','c','a'), ['a','a','a']) == 3
```

| 程式類型 | 實際輸出 | 對生成 expected=3 的 pass bit |
|---|---:|---:|
| membership（包括 c07、c13） | 2 | 0 |
| 保留查詢重複次數（包括 c09、c10） | 6 | 0 |
| 固定官方參考 | 6 | 不作選擇輸入 |

其餘 63 條兩類輸出相同。14 條共同失敗列為 indices `9,10,14,15,27,28,30,42,46,50,51,55,56,57`；除 index 46 外，兩類函式在另十三條均產生相同值但與生成期望不符。例如 index 27 的 tuple 長度只有 5，生成 expected 卻為 6；index 28 對兩個 apple 預期 3。

這個盲區不是「測試完全沒有不同輸出的輸入」：它有一個，但 expected=3 讓二元 pass matrix 將 2 與 6 一同壓為 0。現有選擇器只接收二元矩陣和來源組，刪除列無法創造缺失的區分訊號。這支持此固定池的一個矩陣資訊限制個案，不能估計其自然發生率、跨模型普遍性，或推斷改用輸出值距離就能實際提升 E2。

## 格式異常與環境差異檢查

五份格式異常為 Mbpp/294 的 c09、c11、c13，以及 Mbpp/446 的 c00、c02。原始回覆開頭為 code fence、換行、獨立的 `python` 一行，再接函式定義；不是標準的同一行 ` ```python ` 語言標籤。共同抽取器保留 `python` 這個可被 Python AST 解析的表達式，因此候選被記作 usable，但每次執行都立即 `NameError: name 'python' is not defined`。

它們共佔 5×64=320 次可見 `program_error`，隱藏 base/plus 亦均 fail、details 空。此處「可解析」沒有保證「可執行」，是協議下可解釋的輸出格式／頂層名稱錯誤，不應事後修補它們來改善本次 coverage。它們不是 Mbpp/294 gain 的被選候選，也不是 Mbpp/446 同行正確候選的來源。

兩題的全部可見狀態僅有 pass、assertion_fail、program_error。Mbpp/294 的例外型別為 ValueError 174、TypeError 35、IndexError 15、NameError 192；Mbpp/446 僅有 NameError 128。未記錄 ImportError、ModuleNotFoundError、MemoryError 或 timeout。可見單次最大秒數分別約 0.00662、0.00500，遠低於 0.5 秒限額；關鍵候選只依賴標準庫或內建運算，沒有外部套件差異。

可見執行與 hidden kernel 的依賴／資源環境確實不同，但現有兩個事件無需此差異即可解釋。本文件沒有重跑相同輸入於兩種環境，因此「完全排除所有環境影響」仍不可斷言；也不能將其他未審計 E0 題或未完成 E1 的異常概括為相同原因。

## 統計與推論邊界

ARS validate 的 11 類謬誤已逐項檢視，覆蓋 11/11。這是後驗選取事件的個案解釋，未新增 p 值或確認性檢驗。

| 類別 | 本次處理／限制 |
|---|---|
| Simpson's paradox | 分別列出五 selector；未合併跨資料集或以分層比例推論，反轉檢驗不適用。 |
| Ecological fallacy | 同題多 selector、多候選和 64 列不作獨立樣本；只有兩個去重 task。 |
| Berkson's paradox | 依 gain/盲區事件選案，不能由兩題估計全體程式錯誤機制盛行率。 |
| Collider bias | 事件條件化只用於解釋，未從條件子集估計因果關係或方法效果。 |
| Base-rate neglect | 唯一 gain 為完整 E0 分母的 1/20；同時報告所有 selector 的零 loss 和重複盲區。 |
| Regression to the mean | 未做前後測或重新生成，沒有將重新採樣波動描述為改進。 |
| Survivorship bias | 事件從完整 20 題枚舉；格式失敗保留，不刪除失敗候選來提升數字。 |
| Look-elsewhere effect | 五 selector、全部 20 隨機種子保持可見；不挑唯一有利 selector 或種子作普遍結論。 |
| Garden of forking paths | 本審計未改配置、抽取器、期望值、平局或排除規則；個案解釋明確為後驗。 |
| Correlation versus causation | 不以 coverage 增加推斷來源結構有因果優勢；294 隨機對照完全匹配。 |
| Reverse causality | 沒有從結果反推生成來源具有何種因果依賴；未作方向性統計推論。 |

原報告的 E0 小樣本與未校正多比較限制繼續適用。尤其 dedup_uniform 的 +5 個百分點只是一題變化；已保存的 95% percentile CI 為 [0,+15] 個百分點，不是確認性效果保證。E0 的這些診斷不能拿去修改正在執行的 E1 後再把 E1 當作原配置確認。

## 附錄：完整矩陣、逐候選狀態與生成測試

矩陣依原 candidate 行序及 test 列序列出。為避免逐位複製錯誤，完全相同行只列一次，並給出覆蓋所有 16 行的 candidate 對應；這可無損還原每題完整 16×64 矩陣。每段八位對應 g00 至 g07；每組內依 t00 至 t07。以下表格由凍結 JSON 機械轉寫，pass/exception 數由既存日誌計數。

### Mbpp/294：完整矩陣

| Candidate suffixes | 64 pass bits，八位一組 |
|---|---|
| 00, 02 | `11001001 10100000 11001101 11011100 11000110 11100011 11010110 11101101` |
| 01, 03, 06, 10, 12, 15 | `11001001 10100000 11001001 11011000 11000110 11100010 11010010 11101100` |
| 04, 07 | `11001001 10100000 11001001 11010000 11000100 11100110 11010000 11100000` |
| 05 | `11111001 11101110 11111011 11110000 11111101 11111110 11111001 11110010` |
| 08 | `11101001 10101000 11101001 11011000 11100110 11110010 11011010 11101100` |
| 09, 11, 13 | `00000000 00000000 00000000 00000000 00000000 00000000 00000000 00000000` |
| 14 | `11001001 10100000 11001101 11010100 11000100 11100111 11010100 11100001` |

### Mbpp/294：逐候選狀態

| Candidate suffix | Official label | Visible pass / assertion_fail / program_error | Official base status / details通過數:已執行數 | Official plus status / details通過數:已執行數 |
|---|---:|---|---|---|
| 00 | 1 | 36 / 28 / 0 | pass / 3:3 | pass / 108:108 |
| 01 | 1 | 31 / 4 / 29 | pass / 3:3 | pass / 108:108 |
| 02 | 1 | 36 / 28 / 0 | pass / 3:3 | pass / 108:108 |
| 03 | 1 | 31 / 4 / 29 | pass / 3:3 | pass / 108:108 |
| 04 | 0 | 27 / 24 / 13 | fail / 0:1 | fail / 1:2 |
| 05 | 0 | 48 / 0 / 16 | fail / 0:1 | fail / 0:1 |
| 06 | 1 | 31 / 4 / 29 | pass / 3:3 | pass / 108:108 |
| 07 | 0 | 27 / 24 / 13 | fail / 0:1 | fail / 1:2 |
| 08 | 0 | 37 / 27 / 0 | pass / 3:3 | fail / 97:98 |
| 09 | 0 | 0 / 0 / 64 | fail / 0:0 | fail / 0:0 |
| 10 | 1 | 31 / 4 / 29 | pass / 3:3 | pass / 108:108 |
| 11 | 0 | 0 / 0 / 64 | fail / 0:0 | fail / 0:0 |
| 12 | 1 | 31 / 4 / 29 | pass / 3:3 | pass / 108:108 |
| 13 | 0 | 0 / 0 / 64 | fail / 0:0 | fail / 0:0 |
| 14 | 0 | 32 / 24 / 8 | fail / 0:1 | fail / 1:2 |
| 15 | 1 | 31 / 4 / 29 | pass / 3:3 | pass / 108:108 |

### Mbpp/294：五選擇器及刪組贏家

| Selector | Base | Top-2 | Perturbed | 刪 g00 至 g07 的 winner suffix | Source votes |
|---|---|---|---|---|---|
| uniform | 05 | 05,08 | 05,08 | 05,05,05,05,05,05,05,05 | 05:8 |
| aces_c | 05 | 05,08 | 05,08 | 05,05,05,05,05,05,05,05 | 05:8 |
| dedup_uniform | 05 | 05,14 | 05,00 | 05,05,05,05,05,00,05,05 | 00:1, 05:7 |
| group_equal | 05 | 05,08 | 05,08 | 05,05,05,05,05,05,05,05 | 05:8 |
| group_rep | 05 | 05,14 | 05,14 | 05,05,05,05,14,05,14,05 | 05:6, 14:2 |

### Mbpp/294：全部生成測試

```python
# index 00; Mbpp/294/tests/00/t00
assert max_val([1, 2, 3, 4, 5]) == 5
# index 01; Mbpp/294/tests/00/t01
assert max_val([-1, -2, -3, -4, -5]) == -1
# index 02; Mbpp/294/tests/00/t02
assert max_val([1.5, 2.5, 3.5, 4.5, 5.5]) == 5.5
# index 03; Mbpp/294/tests/00/t03
assert max_val(['a', 'b', 'c', 'd', 'e']) == 'e'
# index 04; Mbpp/294/tests/00/t04
assert max_val([True, False, True, False, True]) == True
# index 05; Mbpp/294/tests/00/t05
assert max_val([None, 0, '0', False]) == '0'
# index 06; Mbpp/294/tests/00/t06
assert max_val([1, 2, 3, 'a', 'b', 'c']) == 'c'
# index 07; Mbpp/294/tests/00/t07
assert max_val([10, 20, 30, 40, 50]) == 50
# index 08; Mbpp/294/tests/01/t00
assert max_val([1, 2, 3, 4, 5]) == 5
# index 09; Mbpp/294/tests/01/t01
assert max_val(['a', 'b', 'c', 'd', 'e']) == 'e'
# index 10; Mbpp/294/tests/01/t02
assert max_val([True, False, True, False]) == True
# index 11; Mbpp/294/tests/01/t03
assert max_val([None, 0, -1, -2]) == None
# index 12; Mbpp/294/tests/01/t04
assert max_val([1.5, 2.5, 3.5, 4.5, 5.5]) == 5.5
# index 13; Mbpp/294/tests/01/t05
assert max_val(['apple', 'banana', 'cherry', 'date']) == 'date'
# index 14; Mbpp/294/tests/01/t06
assert max_val([[], [1, 2], [1, 2, 3]]) == [1, 2, 3]
# index 15; Mbpp/294/tests/01/t07
assert max_val([{1: 'a'}, {2: 'b'}, {3: 'c'}]) == {3: 'c'}
# index 16; Mbpp/294/tests/02/t00
assert max_val([1, 2, 3, 4, 5]) == 5
# index 17; Mbpp/294/tests/02/t01
assert max_val([-1, -2, -3, -4, -5]) == -1
# index 18; Mbpp/294/tests/02/t02
assert max_val([1.5, 2.5, 3.5, 4.5, 5.5]) == 5.5
# index 19; Mbpp/294/tests/02/t03
assert max_val(['a', 'b', 'c', 'd', 'e']) == 'e'
# index 20; Mbpp/294/tests/02/t04
assert max_val([True, False, True, False]) == True
# index 21; Mbpp/294/tests/02/t05
assert max_val([]) == None
# index 22; Mbpp/294/tests/02/t06
assert max_val(['hello', 'world', 'python', 'programming']) == 'world'
# index 23; Mbpp/294/tests/02/t07
assert max_val([0, 0, 0, 0, 0]) == 0
# index 24; Mbpp/294/tests/03/t00
assert max_val([1, 2, 3, 4, 5]) == 5
# index 25; Mbpp/294/tests/03/t01
assert max_val([-1, -2, -3, -4, -5]) == -1
# index 26; Mbpp/294/tests/03/t02
assert max_val(['apple', 'banana', 'cherry']) == 'cherry'
# index 27; Mbpp/294/tests/03/t03
assert max_val([True, False, True]) == True
# index 28; Mbpp/294/tests/03/t04
assert max_val([None, 0, 1]) == 1
# index 29; Mbpp/294/tests/03/t05
assert max_val([]) == None
# index 30; Mbpp/294/tests/03/t06
assert max_val(['a', 1, 2.5, 'z', 3]) == 'z'
# index 31; Mbpp/294/tests/03/t07
assert max_val([1.1, 2.2, 3.3, '4.4']) == '4.4'
# index 32; Mbpp/294/tests/04/t00
assert max_val([1, 2, 3, 4, 5]) == 5
# index 33; Mbpp/294/tests/04/t01
assert max_val([-1, -2, -3, -4, -5]) == -1
# index 34; Mbpp/294/tests/04/t02
assert max_val([1.5, 2.5, 3.5, 4.5, 5.5]) == 5.5
# index 35; Mbpp/294/tests/04/t03
assert max_val(['a', 'b', 'c', 'd', 'e']) == 'e'
# index 36; Mbpp/294/tests/04/t04
assert max_val(['apple', 'banana', 'cherry', 'date', 'elderberry']) == 'elderberry'
# index 37; Mbpp/294/tests/04/t05
assert max_val([True, False, True, False, True]) == True
# index 38; Mbpp/294/tests/04/t06
assert max_val([None, 1, 'two', 3.0, 4]) == 4
# index 39; Mbpp/294/tests/04/t07
assert max_val([[], [1, 2, 3], [4, 5], [6, 7, 8, 9]]) == [6, 7, 8, 9]
# index 40; Mbpp/294/tests/05/t00
assert max_val([1, 2, 3, 4, 5]) == 5
# index 41; Mbpp/294/tests/05/t01
assert max_val([5, 4, 3, 2, 1]) == 5
# index 42; Mbpp/294/tests/05/t02
assert max_val([-1, -2, -3, -4, -5]) == -1
# index 43; Mbpp/294/tests/05/t03
assert max_val([1.5, 2.5, 3.5, 4.5, 5.5]) == 5.5
# index 44; Mbpp/294/tests/05/t04
assert max_val(['apple', 'banana', 'cherry']) == 'cherry'
# index 45; Mbpp/294/tests/05/t05
assert max_val(['z', 'y', 'x', 'w', 'v']) == 'z'
# index 46; Mbpp/294/tests/05/t06
assert max_val([True, False, True, False]) == True
# index 47; Mbpp/294/tests/05/t07
assert max_val([]) == None
# index 48; Mbpp/294/tests/06/t00
assert max_val([1, 2, 3, 4, 5]) == 5
# index 49; Mbpp/294/tests/06/t01
assert max_val([-5, -1, -6, -2]) == -1
# index 50; Mbpp/294/tests/06/t02
assert max_val(['apple', 'banana', 'cherry']) == 'cherry'
# index 51; Mbpp/294/tests/06/t03
assert max_val([True, False, True, False]) == True
# index 52; Mbpp/294/tests/06/t04
assert max_val([1.1, 2.2, 3.3, 4.4, 5.5]) == 5.5
# index 53; Mbpp/294/tests/06/t05
assert max_val([]) == None
# index 54; Mbpp/294/tests/06/t06
assert max_val([None, 0, '0', False]) == 0
# index 55; Mbpp/294/tests/06/t07
assert max_val([[], [1], [1, 2], [1, 2, 3]]) == [1, 2, 3]
# index 56; Mbpp/294/tests/07/t00
assert max_val([1, 2, 3, 4, 5]) == 5
# index 57; Mbpp/294/tests/07/t01
assert max_val([-1, -2, -3, -4, -5]) == -1
# index 58; Mbpp/294/tests/07/t02
assert max_val([0, 0, 0, 0, 0]) == 0
# index 59; Mbpp/294/tests/07/t03
assert max_val(['a', 'b', 'c', 'd', 'e']) == 'e'
# index 60; Mbpp/294/tests/07/t04
assert max_val(['Python', 3, 2, 4, 5, 'version']) == 5
# index 61; Mbpp/294/tests/07/t05
assert max_val([None, True, False, 0, 1, -1]) == 1
# index 62; Mbpp/294/tests/07/t06
assert max_val(['hello', 'world', 'Python', 'code']) == 'world'
# index 63; Mbpp/294/tests/07/t07
assert max_val([]) == None
```

### Mbpp/446：完整矩陣

| Candidate suffixes | 64 pass bits，八位一組 |
|---|---|
| 00, 02 | `00000000 00000000 00000000 00000000 00000000 00000000 00000000 00000000` |
| 01, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14, 15 | `11111111 10011100 11111111 11100101 11111111 11011101 11001110 00111111` |

### Mbpp/446：逐候選狀態

| Candidate suffix | Official label | Visible pass / assertion_fail / program_error | Official base status / details通過數:已執行數 | Official plus status / details通過數:已執行數 |
|---|---:|---|---|---|
| 00 | 0 | 0 / 0 / 64 | fail / 0:0 | fail / 0:0 |
| 01 | 0 | 50 / 14 / 0 | pass / 3:3 | fail / 1:2 |
| 02 | 0 | 0 / 0 / 64 | fail / 0:0 | fail / 0:0 |
| 03 | 0 | 50 / 14 / 0 | pass / 3:3 | fail / 1:2 |
| 04 | 0 | 50 / 14 / 0 | pass / 3:3 | fail / 1:2 |
| 05 | 0 | 50 / 14 / 0 | pass / 3:3 | fail / 1:2 |
| 06 | 0 | 50 / 14 / 0 | pass / 3:3 | fail / 1:2 |
| 07 | 0 | 50 / 14 / 0 | pass / 3:3 | fail / 1:2 |
| 08 | 0 | 50 / 14 / 0 | pass / 3:3 | fail / 1:2 |
| 09 | 1 | 50 / 14 / 0 | pass / 3:3 | pass / 104:104 |
| 10 | 1 | 50 / 14 / 0 | pass / 3:3 | pass / 104:104 |
| 11 | 0 | 50 / 14 / 0 | pass / 3:3 | fail / 1:2 |
| 12 | 0 | 50 / 14 / 0 | pass / 3:3 | fail / 1:2 |
| 13 | 0 | 50 / 14 / 0 | pass / 3:3 | fail / 1:2 |
| 14 | 0 | 50 / 14 / 0 | pass / 3:3 | fail / 1:2 |
| 15 | 0 | 50 / 14 / 0 | pass / 3:3 | fail / 1:2 |

### Mbpp/446：五選擇器及刪組贏家

| Selector | Base | Top-2 | Perturbed | 刪 g00 至 g07 的 winner suffix | Source votes |
|---|---|---|---|---|---|
| uniform | 07 | 07,13 | 07,13 | 07,07,07,07,07,07,07,07 | 07:8 |
| aces_c | 07 | 07,13 | 07,13 | 07,07,07,07,07,07,07,07 | 07:8 |
| dedup_uniform | 07 | 07,13 | 07,13 | 07,07,07,07,07,07,07,07 | 07:8 |
| group_equal | 07 | 07,13 | 07,13 | 07,07,07,07,07,07,07,07 | 07:8 |
| group_rep | 07 | 07,13 | 07,13 | 07,07,07,07,07,07,07,07 | 07:8 |

### Mbpp/446：全部生成測試

```python
# index 00; Mbpp/446/tests/00/t00
assert count_Occurrence(('a', 'a', 'c', 'b', 'd'), ['a', 'b']) == 3
# index 01; Mbpp/446/tests/00/t01
assert count_Occurrence(('x', 'y', 'z'), ['a', 'b']) == 0
# index 02; Mbpp/446/tests/00/t02
assert count_Occurrence(('1', '2', '2', '3', '1', '1'), ['1', '2']) == 5
# index 03; Mbpp/446/tests/00/t03
assert count_Occurrence(('apple', 'banana', 'cherry', 'apple'), ['apple', 'cherry']) == 3
# index 04; Mbpp/446/tests/00/t04
assert count_Occurrence((), ['a', 'b']) == 0
# index 05; Mbpp/446/tests/00/t05
assert count_Occurrence(('hello', 'world'), ['hello', 'world']) == 2
# index 06; Mbpp/446/tests/00/t06
assert count_Occurrence(('123', '456', '789', '123'), ['123']) == 2
# index 07; Mbpp/446/tests/00/t07
assert count_Occurrence(('True', 'False', 'True', 'True'), ['True']) == 3
# index 08; Mbpp/446/tests/01/t00
assert count_Occurrence(('apple', 'banana', 'cherry', 'apple'), ['apple', 'cherry']) == 3
# index 09; Mbpp/446/tests/01/t01
assert count_Occurrence(('python', 'java', 'python', 'c++'), ['python', 'java']) == 2
# index 10; Mbpp/446/tests/01/t02
assert count_Occurrence((1, 2, 3, 4, 5, 1, 2, 1), [1, 2]) == 4
# index 11; Mbpp/446/tests/01/t03
assert count_Occurrence(('a', 'b', 'c'), ['d', 'e']) == 0
# index 12; Mbpp/446/tests/01/t04
assert count_Occurrence(('hello', 'world'), ['hello', 'world']) == 2
# index 13; Mbpp/446/tests/01/t05
assert count_Occurrence(('a', 'b', 'c', 'a', 'b', 'c', 'a', 'b', 'c'), ['a', 'b', 'c']) == 9
# index 14; Mbpp/446/tests/01/t06
assert count_Occurrence((True, False, True), [True, False]) == 2
# index 15; Mbpp/446/tests/01/t07
assert count_Occurrence(('123', '456', '123'), ['123', '456', '789']) == 2
# index 16; Mbpp/446/tests/02/t00
assert count_Occurrence(('a', 'a', 'c', 'b', 'd'), ['a', 'b']) == 3
# index 17; Mbpp/446/tests/02/t01
assert count_Occurrence(('x', 'y', 'z'), ['x', 'y', 'z']) == 3
# index 18; Mbpp/446/tests/02/t02
assert count_Occurrence(('a', 'b', 'c', 'd'), ['e', 'f']) == 0
# index 19; Mbpp/446/tests/02/t03
assert count_Occurrence(('1', '2', '3'), ['1', '2', '3', '4', '5']) == 3
# index 20; Mbpp/446/tests/02/t04
assert count_Occurrence(('apple', 'banana', 'apple'), ['apple', 'orange']) == 2
# index 21; Mbpp/446/tests/02/t05
assert count_Occurrence((), ['a', 'b']) == 0
# index 22; Mbpp/446/tests/02/t06
assert count_Occurrence(('a', 'a', 'a', 'a'), ['a']) == 4
# index 23; Mbpp/446/tests/02/t07
assert count_Occurrence(('a', 'b', 'c', 'd'), ['a', 'b', 'c', 'd']) == 4
# index 24; Mbpp/446/tests/03/t00
assert count_Occurrence(('a', 'a', 'c', 'b', 'd'), ['a', 'b']) == 3
# index 25; Mbpp/446/tests/03/t01
assert count_Occurrence(('x', 'y', 'z'), ['x', 'y', 'z']) == 3
# index 26; Mbpp/446/tests/03/t02
assert count_Occurrence(('m', 'n', 'o'), ['p', 'q', 'r']) == 0
# index 27; Mbpp/446/tests/03/t03
assert count_Occurrence(('1', '2', '3', '2', '1'), ['1', '2', '3']) == 6
# index 28; Mbpp/446/tests/03/t04
assert count_Occurrence(('apple', 'banana', 'apple'), ['apple']) == 3
# index 29; Mbpp/446/tests/03/t05
assert count_Occurrence(('True', 'False', 'True'), ['True', 'False']) == 3
# index 30; Mbpp/446/tests/03/t06
assert count_Occurrence((None, None, 'None'), [None]) == 3
# index 31; Mbpp/446/tests/03/t07
assert count_Occurrence(('a', 'b', 'c'), ['a', 'b', 'c', 'd']) == 3
# index 32; Mbpp/446/tests/04/t00
assert count_Occurrence(('x', 'y', 'z'), ['x', 'y', 'z']) == 3
# index 33; Mbpp/446/tests/04/t01
assert count_Occurrence(('1', '2', '3'), ['4', '5']) == 0
# index 34; Mbpp/446/tests/04/t02
assert count_Occurrence((), ['a', 'b', 'c']) == 0
# index 35; Mbpp/446/tests/04/t03
assert count_Occurrence(('a', 'b', 'a', 'b', 'a'), ['a']) == 3
# index 36; Mbpp/446/tests/04/t04
assert count_Occurrence(('a', 'b', 'c', 'd'), ['a', 'b', 'c', 'd']) == 4
# index 37; Mbpp/446/tests/04/t05
assert count_Occurrence(('a', 'b', 'c', 'd'), ['a', 'b', 'c', 'd', 'e']) == 4
# index 38; Mbpp/446/tests/04/t06
assert count_Occurrence(('1', '2', '3', '4'), ['1', '2', '3', '4']) == 4
# index 39; Mbpp/446/tests/04/t07
assert count_Occurrence(('a', 'b', 'c', 'd'), []) == 0
# index 40; Mbpp/446/tests/05/t00
assert count_Occurrence(('a', 'a', 'c', 'b', 'd'), ['a', 'b']) == 3
# index 41; Mbpp/446/tests/05/t01
assert count_Occurrence(('x', 'y', 'z'), ['x', 'y', 'z']) == 3
# index 42; Mbpp/446/tests/05/t02
assert count_Occurrence(('1', '2', '2', '3'), ['2', '3']) == 2
# index 43; Mbpp/446/tests/05/t03
assert count_Occurrence((), ['a', 'b']) == 0
# index 44; Mbpp/446/tests/05/t04
assert count_Occurrence(('a', 'b', 'c'), []) == 0
# index 45; Mbpp/446/tests/05/t05
assert count_Occurrence(('a', 'a', 'a'), ['a', 'b']) == 3
# index 46; Mbpp/446/tests/05/t06
assert count_Occurrence(('a', 'b', 'c', 'a'), ['a', 'a', 'a']) == 3
# index 47; Mbpp/446/tests/05/t07
assert count_Occurrence(('a', 'b', 'c', 'd', 'e'), ['f', 'g']) == 0
# index 48; Mbpp/446/tests/06/t00
assert count_Occurrence(('a', 'b', 'c', 'd'), ['a', 'b', 'c', 'd']) == 4
# index 49; Mbpp/446/tests/06/t01
assert count_Occurrence(('a', 'b', 'c', 'd'), ['a', 'b', 'e', 'f']) == 2
# index 50; Mbpp/446/tests/06/t02
assert count_Occurrence(('1', '2', '3', '4', '5', '1', '2'), ['1', '2', '3']) == 3
# index 51; Mbpp/446/tests/06/t03
assert count_Occurrence(('apple', 'banana', 'cherry', 'apple'), ['apple', 'banana']) == 2
# index 52; Mbpp/446/tests/06/t04
assert count_Occurrence(('a', 'a', 'a', 'a'), ['a']) == 4
# index 53; Mbpp/446/tests/06/t05
assert count_Occurrence(('a', 'b', 'c', 'd'), []) == 0
# index 54; Mbpp/446/tests/06/t06
assert count_Occurrence((), ['a', 'b', 'c']) == 0
# index 55; Mbpp/446/tests/06/t07
assert count_Occurrence(('x', 'y', 'z'), ['w', 'x', 'y', 'z']) == 2
# index 56; Mbpp/446/tests/07/t00
assert count_Occurrence(('x', 'y', 'x'), ['x', 'y', 'z']) == 2
# index 57; Mbpp/446/tests/07/t01
assert count_Occurrence(('1', '2', '3', '2'), ['2', '3']) == 2
# index 58; Mbpp/446/tests/07/t02
assert count_Occurrence(('a', 'b', 'c', 'd'), ['e', 'f']) == 0
# index 59; Mbpp/446/tests/07/t03
assert count_Occurrence(('apple', 'banana', 'apple', 'orange'), ['apple']) == 2
# index 60; Mbpp/446/tests/07/t04
assert count_Occurrence(('True', 'False', 'True'), ['True']) == 2
# index 61; Mbpp/446/tests/07/t05
assert count_Occurrence((None, None, 'None'), [None]) == 2
# index 62; Mbpp/446/tests/07/t06
assert count_Occurrence((1, 2, 3, 4, 5), [1, 2, 3, 4, 5]) == 5
# index 63; Mbpp/446/tests/07/t07
assert count_Occurrence((), ['a', 'b']) == 0
```
