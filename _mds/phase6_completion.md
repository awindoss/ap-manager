# Phase 6 完成报告：导入与导出

> 完成日期：2026-11-06
> 代码基线：Phase 1 + 2 + 3 + 4 + 5 工作树
> 验证环境：Python 3.11.15 / PySide6 6.11.1 / pytest 9.1.1（Windows）
> 验证结果：**364 项测试全部通过**（Phase 5 基线上新增 64 项）

---

## 一、结论

`_mds/plan.md` 第 35 节 Phase 6 的 9 项检查全部完成，`_mds/stage.md` Phase 6
的 6.1 ~ 6.4 全部落地：

| stage.md 任务 | 实现 | 验证 |
|---|---|---|
| 6.1 `services/exporter.py` | 扁平 `nodes` + `edges` 文档；`n1..nN` 稳定外部 ID；PDF 路径相对化，可选复制到导出目录 `books/`；自定义图标复制到导出目录 `icons/`；原子写入 `library.json` | `tests/test_exporter.py`（9 项） |
| 6.2 `services/importer.py` | 版本/结构校验；`external_id → local_db_id` 映射；edges 重建；PDF 路径按 JSON 所在目录重新定位；图标复制到本地 `icons/`；缺失文件仅告警；整体事务，失败回滚 | `tests/test_importer.py`（15 项） |
| 6.3 `utils/json_utils.py` | `load_library_document()` / `validate_json_schema()` / `parse_library_document()`；重复 ID、重复边、自环、未知端点、循环、字段类型检查 | `tests/test_json_utils.py`（19 项） |
| 6.4 UI 集成 | 文件菜单“导入图书馆… / 导出图书馆…”（Ctrl+I / Ctrl+E）；导入前询问“追加 / 替换”；导出前询问是否复制 PDF、是否覆盖；完成后汇总提示并刷新树 | `tests/test_main_window_phase6.py`（10 项） |

额外交付：

- `Database.insert_graph()` / `clear_all()`：整张图在**一个事务**内写入或替换，
  导入失败不会留下半个图书馆（plan.md §38）。
- 导出支持 `copy_pdfs=True`，把 PDF 一并复制到 `books/`，导出目录可整体复制
  到另一台电脑；相同文件只复制一次。
- 导入自定义图标时增加目录约束（只接受导入目录内的文件），并复用目标
  `icons/` 中已存在的文件；`icon_utils.import_custom_icon()` 也会保留已有的
  `<stem>_<contenthash>` 名称，保证“导出 → 导入 → 再导出”文档逐字节稳定，
  不会每次迁移都给图标名再追加一层哈希。
- `path_manager.make_export_reference()` / `resolve_imported_reference()` 集中
  处理导出、导入两个方向的路径换算。
- `AppController.export_library()` / `import_library()` / `get_library_counts()`
  作为 View 与 Service 之间的入口，延续 plan.md §27 的调用方向。

---

## 二、关键设计决定

1. **扁平图文档，而不是嵌套 children**
   导出只写 `nodes` + `edges` 两张表对应的扁平数组（plan.md §23.2）。
   嵌套树无法无损表示多父级关系，`n3` 同时出现在两个父级下时，只有 flat
   edges 能保留全部位置和 `sort_order`。

2. **外部 ID 与本地 ID 彻底解耦**
   导出时按节点数据库 ID 顺序生成 `n1..nN`；导入时逐节点插入新行，记录
   `external_id → local_id`，再按映射重建 edges（plan.md §25）。
   因此导入文件可以在任意数据库中使用，不会与自增主键冲突；同一文件重复
   导入（merge 模式）会生成一套新的节点，这是“追加”的预期语义。

3. **导入只有两种语义：追加与替换**
   - `merge`：保留现有图，把导入图追加进去；
   - `replace`：在**同一个事务**里先清空 edges/nodes，再写入导入图。
   任一校验或 SQLite 失败都会整体回滚，旧书库保持原样（plan.md §38）。
   清除只针对数据库分类，磁盘 PDF 永不删除（plan.md §40）。

4. **先完整校验，再写数据库**
   `utils/json_utils.py` 在打开数据库写入之前完成：格式名、版本号、节点字段、
   PDF/图标类型、重复节点 ID、重复边、自环、未知端点、全图无环检查。
   错误消息直接面向用户（中文、指明第几条/哪个节点），UI 不需要再翻译异常。

5. **路径换算统一由 `path_manager` 负责**
   - 导出：先把存储路径解析为绝对路径，再相对 `export_dir` 写成
     `./books/a.pdf` / `../books/a.pdf`；不同盘符无法相对表示时保留绝对路径。
   - 导入：先把 JSON 里的相对路径按 `library.json` 所在目录解析为绝对路径，
     再按 `make_stored_path` 的既有规则存成“应用根内相对 / 根外绝对”。
   - 缺失文件只记录告警，引用仍写入数据库，供 Phase 7 的“重新定位”修复
     （plan.md §22、§24）。

6. **图标是可迁移文件，不是绝对路径**
   导出时只复制 `icons/` 内的自定义图标（`icon_utils.get_icon_path` 已有
   containment 检查），JSON 写 `icons/<name>`；导入时只接受导入目录内的
   图标文件，复制到本地 `icons/`。找不到或越界的图标会清空并告警，节点本身
   照常导入。

7. **`library.json` 原子写入**
   先写 `<name>.tmp` 再 `os.replace`，导出中途失败不会截断上一次的导出文件。

8. **UI 只做选择与汇总**
   菜单动作只负责选文件/目录、询问追加或替换、是否复制 PDF；真正的读写全部
   经过 Controller → Service。导入成功后统一 `refresh()`，恢复旧的展开路径
   与选中项（Phase 2/3 的刷新机制直接复用）。

---

## 三、文件清单

### 新增

```text
utils/json_utils.py                     # 交换格式读取、字段校验、版本检查、无环检查
services/exporter.py                    # 整库导出、PDF/图标复制、原子写 JSON
services/importer.py                    # 整库导入、ID 映射、路径/图标重定位、事务写入

tests/test_json_utils.py                # 19 项
tests/test_exporter.py                  # 9 项
tests/test_importer.py                  # 15 项
tests/test_controller_import_export.py  # 5 项
tests/test_main_window_phase6.py        # 10 项
```

### 修改

```text
utils/constants.py          # 版本支持列表、导入模式、JSON 键名、library.json 文件名与过滤器
services/path_manager.py    # make_export_reference / resolve_imported_reference
models/database.py          # insert_graph / clear_all（单事务批量写入）
models/library.py           # get_all_edges / insert_graph / clear_library
controllers/app_controller.py  # export_library / import_library / get_library_counts
views/main_window.py        # 文件菜单、导入模式/覆盖/复制 PDF 询问、结果汇总
utils/icon_utils.py         # 保留已有 <stem>_<contenthash> 图标名（迁移稳定）
tests/test_path_manager.py  # 新增 5 项导出/导入路径换算测试
tests/test_icon_utils.py    # 新增 1 项 content-addressed 图标重导入测试
_mds/plan.md                # Phase 6 九项勾选
```

### 测试分布

| 文件 | 项数 | 说明 |
|---|---:|---|
| `tests/test_json_utils.py` | 19 | 格式/版本/字段/重复/无边环 |
| `tests/test_exporter.py` | 9 | 扁平文档、外部 ID、路径、复制、告警、覆盖 |
| `tests/test_importer.py` | 15 | ID 映射、edges、合并/替换、路径/图标、回滚、往返 |
| `tests/test_controller_import_export.py` | 5 | 控制器出入口、参数校验、计数 |
| `tests/test_main_window_phase6.py` | 10 | 菜单、导入刷新、替换、失败提示、导出确认 |
| `tests/test_path_manager.py`（新增部分） | 5 | 导出/导入路径换算 |
| `tests/test_icon_utils.py`（新增部分） | 1 | content-addressed 图标重导入 |
| **新增合计** | **64** | |
| 既有测试 | 300 | 全部通过，无回归 |

---

## 四、验证方式

```powershell
# 项目根目录
D:\Anaconda\envs\pyside\python.exe -m pytest
```

本次实际执行结果：

```text
364 passed in 16.40s
```

GUI 冒烟使用真实 Windows 平台渲染，截图保存在 `logs/`（该目录被 `.gitignore`
忽略，属于本地验证产物）：

- `logs/phase6_main_window.png`：7 个节点、7 条关系、10 个显示实例；
  `马克思` 同时在“马列”和“西欧哲学家”下，`政治经济学批判` 在三个显示实例
  中出现，右侧 `×2` 角标与状态栏计数正确。
- `logs/phase6_imported.png`：同一书库导出（复制 3 个 PDF）后再导入全新
  数据库，界面与左侧展开结构完全一致，缺失 PDF 为 0。
- `logs/phase6_export/library.json`：`./books/capital_1.pdf` 等相对路径、
  `format/version/nodes/edges` 字段与 plan.md §23.2 一致。

> 环境备注：当前 DSH Windows 文件沙箱中，pytest 的 `tmp_path`（`mode=0o700`）
> 目录不可读写；本次沿用 `logs/run_pytest.py` 启动器把临时目录模式放宽到
> `0o755` 后运行。普通开发机直接使用上面的 `pytest` 命令即可。

---

## 五、已知边界

- `merge` 模式按“导入一套新图”处理，不按名称合并节点；重复导入同一文件会
  得到重复节点。需要干净结果时使用“替换当前书库”。
- 导入不会把 PDF 复制进应用的 `books/`，只把引用重定位到 JSON 所在目录
  （与 stage.md 6.2 一致）。要得到可整体迁移的目录，导出时选择“复制 PDF”。
- 不复制 PDF 且导出目录不在书库根内时，JSON 会出现 `../...` 相对路径或
  跨盘符绝对路径；只移动导出目录本身会导致这些引用失效。
- 导出不包含 `created_time` / `updated_time`（plan.md §23.2 未定义）；重新
  导入后时间戳为导入时刻。
- 重复导出到同一目录不会清理上一次遗留的、已不再引用的 `books/` 或
  `icons/` 文件；只保证本次引用的文件可用。
- `replace` 模式只清空数据库分类，不删除磁盘 PDF（plan.md §40）。

---

## 六、后续阶段衔接

- **Phase 7**：`ImportResult.id_map` 可用于导入后定位/展开新节点；
  `get_library_counts()` 可直接用于搜索面板或状态栏；`json_utils` 的版本
  检查与 `SUPPORTED_LIBRARY_VERSIONS` 可在未来格式升级时扩展为多版本迁移器。
- 搜索、窗口状态记忆与日志完善属于 Phase 7，本阶段未改动这些行为。
- Phase 8 的注释文件可以继续放在 `metadata` 或独立表中；导入/导出已按
  原样保留 `metadata` 字典，不会丢失未来字段。

---

*本报告依据 `_mds/plan.md`、`_mds/stage.md` 与 Phase 6 实际代码编写。*
