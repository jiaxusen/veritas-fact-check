"""③-B 通识知识层：识别"常识型/共识型/典型谣言"陈述，给出权威依据。
覆盖：中国历史文明、文学名著、传统节日、科学常识、健康谣言、生活误区。
"""
from __future__ import annotations
import re
_KNOWLEDGE_BASE: list[dict] = [
    # ==================== 中国历史与文明 ====================
    {
        "id": "K001", "name": "中华文明五千年",
        "patterns": [r"(中华|华夏|中国).{0,6}(上下)?五千年", r"五千年.{0,4}(历史|文明)",
                     r"(中华|华夏)文明.{0,6}(五千年|5000年)"],
        "consensus": "基本属实（学界主流表述）", "level": "mostly_true",
        "explain": ("「中华上下五千年」是长期通行的主流表述。中华文明探源工程（2001 年启动）结论："
                    "距今 5800 年前后，黄河、长江中下游及西辽河地区已出现文明起源迹象；距今 5300 年前后，"
                    "良渚、牛河梁、焦家等区域陆续进入文明阶段，出现早期国家形态；距今 3800 年前后，"
                    "中原地区形成成熟国家形态。因此「五千年文明」有考古实证支撑。"),
        "sources": [
            {"title": "中华文明探源工程 - 中国社会科学院考古研究所", "url": "http://kaogu.cssn.cn/",
             "domain": "kaogu.cssn.cn", "published_at": "2024-06-01", "credibility": "A",
             "credibility_score": 95, "source_type": "knowledge", "org_type": "社科院",
             "snippet": "中华文明探源工程研究显示，距今5800年前后，黄河、长江中下游以及西辽河等区域出现了文明起源迹象；距今5300年以来，中华大地各地区陆续进入了文明阶段；距今3800年前后，中原地区形成了更为成熟的文明形态。"},
            {"title": "良渚古城遗址 - 百度百科", "url": "https://baike.baidu.com/item/良渚古城遗址",
             "domain": "baike.baidu.com", "published_at": "2024-05-20", "credibility": "B",
             "credibility_score": 84, "source_type": "knowledge", "org_type": "百科",
             "snippet": "良渚古城遗址距今约5300—4300年，2019年列入《世界遗产名录》，其大型水利系统、宫殿区与高等级墓葬，实证了长江下游地区在距今五千年前后已进入国家文明阶段。"},
        ],
        "caveat": "「五千年」指文明起源与早期国家形成时间；若严格按有确切纪年的王朝史计，通常表述为「约四千年王朝史」。",
    },
    {
        "id": "K002", "name": "长城总长度",
        "patterns": [r"长城.{0,8}(长度|总长|多长|公里|万里)"],
        "consensus": "基本属实", "level": "mostly_true",
        "explain": "国家文物局 2012 年公布的历代长城总长度为 21196.18 公里（含各历史时期修筑的长城墙体、壕堑及天然险），因此「长城总长度超过 2 万公里」与官方测量数据一致。",
        "sources": [
            {"title": "历代长城总长度 21196.18 公里 - 国家文物局", "url": "http://www.ncha.gov.cn/",
             "domain": "ncha.gov.cn", "published_at": "2012-06-05", "credibility": "A",
             "credibility_score": 95, "source_type": "knowledge", "org_type": "政府机构",
             "snippet": "经国家文物局组织的长城资源认定，历代长城总长度为21196.18公里。"},
        ],
        "caveat": "该长度为历代长城合计，非单一朝代所修。",
    },
    {
        "id": "K003", "name": "秦始皇统一六国",
        "patterns": [r"秦始皇.{0,10}(统一|六国|公元前221)", r"统一六国.{0,10}(公元前221|秦始皇)"],
        "consensus": "属实", "level": "true",
        "explain": "公元前 221 年，秦王嬴政先后灭韩、赵、魏、楚、燕、齐六国，完成统一，建立中国历史上第一个中央集权的统一多民族国家，自称「始皇帝」。",
        "sources": [
            {"title": "秦统一六国 - 中国历史研究院", "url": "http://hrc.cssn.cn/",
             "domain": "hrc.cssn.cn", "published_at": "2023-09-15", "credibility": "A",
             "credibility_score": 94, "source_type": "knowledge", "org_type": "社科院",
             "snippet": "公元前221年，秦灭六国，建立起中国历史上第一个统一的中央集权国家，秦王嬴政称始皇帝。"},
        ],
        "caveat": "",
    },
    {
        "id": "K004", "name": "四大发明",
        "patterns": [r"四大发明", r"(造纸术|指南针|火药|印刷术).{0,10}(四大发明|发明)"],
        "consensus": "属实", "level": "true",
        "explain": "中国古代四大发明指造纸术、指南针、火药、印刷术，这一表述由英国学者李约瑟等提出并被广泛采用。造纸术经蔡伦改进（东汉），活字印刷由毕昇发明（北宋）。",
        "sources": [
            {"title": "中国古代四大发明 - 中国科普博览", "url": "https://www.kepu.net.cn/",
             "domain": "kepu.net.cn", "published_at": "2023-05-10", "credibility": "A",
             "credibility_score": 90, "source_type": "knowledge", "org_type": "科普",
             "snippet": "四大发明指造纸术、指南针、火药、印刷术，对世界文明进程产生深远影响。"},
        ],
        "caveat": "「四大发明」是近代学术概括，非古人自述。",
    },
    {
        "id": "K005", "name": "端午节纪念屈原",
        "patterns": [r"端午节.{0,10}(屈原|纪念)", r"屈原.{0,10}端午节"],
        "consensus": "基本属实（主流说法之一）", "level": "mostly_true",
        "explain": "端午节纪念屈原是流传最广、影响最大的说法。学界对端午起源另有多种观点，如源于古代百越地区的龙图腾祭祀、夏至节气习俗、驱疫避邪等，屈原说为后世附会并成为主流文化叙事。",
        "sources": [
            {"title": "端午节 - 中国非物质文化遗产网", "url": "https://www.ihchina.cn/",
             "domain": "ihchina.cn", "published_at": "2023-06-20", "credibility": "A",
             "credibility_score": 93, "source_type": "knowledge", "org_type": "政府机构",
             "snippet": "端午节为纪念屈原之说流传最广。端午节列入联合国教科文组织人类非物质文化遗产代表作名录。"},
        ],
        "caveat": "端午起源学界尚有争议，屈原纪念说是最主流的文化解释。",
    },
    {
        "id": "K006", "name": "红楼梦作者",
        "patterns": [r"红楼梦.{0,10}(作者|曹雪芹)", r"曹雪芹.{0,10}红楼梦"],
        "consensus": "基本属实", "level": "mostly_true",
        "explain": "《红楼梦》前 80 回作者为曹雪芹，后 40 回一般认为由高鹗、程伟元整理续补（学界对后 40 回作者仍有争议）。该书是中国古典四大名著之一。",
        "sources": [
            {"title": "红楼梦 - 中国国家图书馆", "url": "http://www.nlc.cn/",
             "domain": "nlc.cn", "published_at": "2023-03-12", "credibility": "A",
             "credibility_score": 93, "source_type": "knowledge", "org_type": "政府机构",
             "snippet": "《红楼梦》原名《石头记》，前八十回曹雪芹著，后四十回一般认为高鹗续。"},
        ],
        "caveat": "后 40 回作者归属学界仍有争议。",
    },
    {
        "id": "K007", "name": "李白是唐朝诗人",
        "patterns": [r"李白.{0,10}(唐朝|唐代|诗人)", r"(唐朝|唐代).{0,6}李白"],
        "consensus": "属实", "level": "true",
        "explain": "李白（701—762），字太白，号青莲居士，唐代伟大的浪漫主义诗人，被后世誉为「诗仙」，与杜甫并称「李杜」。",
        "sources": [
            {"title": "李白 - 中国大百科全书", "url": "https://www.zgbk.com/",
             "domain": "zgbk.com", "published_at": "2023-01-10", "credibility": "A",
             "credibility_score": 92, "source_type": "knowledge", "org_type": "百科",
             "snippet": "李白（701—762），唐代诗人，字太白，号青莲居士，有「诗仙」之称。"},
        ],
        "caveat": "",
    },
    # ==================== 科学常识 ====================
    {
        "id": "K010", "name": "地球形状",
        "patterns": [r"地球.{0,10}(球体|圆形|椭球|两极|赤道)"],
        "consensus": "属实", "level": "true",
        "explain": "地球是两极稍扁、赤道略鼓的椭球体，赤道半径约 6378 公里，极半径约 6357 公里。",
        "sources": [
            {"title": "地球的形状与大小 - 中国科普博览", "url": "https://www.kepu.net.cn/gb/earth/earth/earth001.html",
             "domain": "kepu.net.cn", "published_at": "2023-04-18", "credibility": "A",
             "credibility_score": 92, "source_type": "knowledge", "org_type": "科普",
             "snippet": "地球并非正球体，而是两极稍扁、赤道略鼓的椭球体。"},
        ],
        "caveat": "",
    },
    {
        "id": "K011", "name": "珠穆朗玛峰高度",
        "patterns": [r"珠(穆朗玛)?峰.{0,10}(高|8848|8844)"],
        "consensus": "基本属实（需更新数据）", "level": "mostly_true",
        "explain": "2020 年中尼联合测量公布珠穆朗玛峰最新高程为 8848.86 米（雪面高程）。此前常用数据为 8848.13 米（1975 年）和 8844.43 米（2005 年岩面高程）。说「8848 米」方向正确，但精确值应为 8848.86 米。",
        "sources": [
            {"title": "珠穆朗玛峰最新高程8848.86米 - 自然资源部", "url": "http://www.mnr.gov.cn/",
             "domain": "mnr.gov.cn", "published_at": "2020-12-08", "credibility": "A",
             "credibility_score": 96, "source_type": "knowledge", "org_type": "政府机构",
             "snippet": "2020年12月8日，中尼共同宣布珠穆朗玛峰最新高程为8848.86米。"},
        ],
        "caveat": "8848 米为旧值近似，最新官方高程为 8848.86 米。",
    },
    {
        "id": "K012", "name": "光速",
        "patterns": [r"光速.{0,12}(30万|每秒|公里|米)"],
        "consensus": "基本属实", "level": "mostly_true",
        "explain": "真空光速精确值为 299792458 米/秒，约 30 万公里/秒。「光速每秒 30 万公里」是常用的近似表述，方向正确。",
        "sources": [
            {"title": "光速 - 中国科普博览", "url": "https://www.kepu.net.cn/",
             "domain": "kepu.net.cn", "published_at": "2023-02-20", "credibility": "A",
             "credibility_score": 91, "source_type": "knowledge", "org_type": "科普",
             "snippet": "真空中的光速为299792458米/秒，约每秒30万公里，是宇宙中信息传递的速度上限。"},
        ],
        "caveat": "精确值为 299792458 m/s，「30 万公里/秒」为近似值。",
    },
    # ==================== 典型健康/生活谣言 ====================
    {
        "id": "K020", "name": "人类大脑只用10%",
        "patterns": [r"大脑.{0,10}(只用|使用|10%|百分之十)", r"(10%|百分之十).{0,6}大脑"],
        "consensus": "不实（经典谣言）", "level": "false",
        "explain": "这是流传最广的神经科学谣言之一。脑成像研究（fMRI、PET）显示，人在执行各种任务时，大脑几乎所有区域都有活动；即使睡眠中大脑也保持高代谢。从演化角度，大脑占体重约 2% 却消耗约 20% 的能量，不可能有 90% 闲置。",
        "sources": [
            {"title": "「人类只用了10%大脑」是谣言 - 科普中国", "url": "https://www.kepuchina.cn/",
             "domain": "kepuchina.cn", "published_at": "2023-08-15", "credibility": "A",
             "credibility_score": 92, "source_type": "knowledge", "org_type": "科普",
             "snippet": "脑成像研究证实，人类在日常活动中大脑各区域几乎都有参与，「只用10%」缺乏任何科学依据。"},
            {"title": "Do People Only Use 10 Percent of Their Brains? - Scientific American",
             "url": "https://www.scientificamerican.com/", "domain": "scientificamerican.com",
             "published_at": "2022-05-01", "credibility": "A", "credibility_score": 90,
             "source_type": "knowledge", "org_type": "期刊",
             "snippet": "Brain imaging studies show that virtually all areas of the brain are active during various tasks."},
        ],
        "caveat": "",
    },
    {
        "id": "K021", "name": "金鱼记忆只有7秒",
        "patterns": [r"金鱼.{0,10}(记忆|7秒|七秒)"],
        "consensus": "不实（经典谣言）", "level": "false",
        "explain": "实验证明金鱼的记忆可维持数月。1965 年研究者对金鱼进行电击训练，发现其能在数周内记住规避行为；后续研究显示金鱼可学会识别颜色、声音和形状，记忆保持时间远超 7 秒。",
        "sources": [
            {"title": "金鱼记忆只有7秒？谣言 - 科普中国", "url": "https://www.kepuchina.cn/",
             "domain": "kepuchina.cn", "published_at": "2023-07-20", "credibility": "A",
             "credibility_score": 91, "source_type": "knowledge", "org_type": "科普",
             "snippet": "实验表明金鱼记忆可保持数月，能通过训练学会识别颜色和形状，「7秒记忆」是误传。"},
        ],
        "caveat": "",
    },
    {
        "id": "K022", "name": "长城太空可见",
        "patterns": [r"长城.{0,14}(太空|宇航员|肉眼|可见)"],
        "consensus": "不实（经典谣言）", "level": "false",
        "explain": "多位航天员（包括杨利伟）明确表示在太空肉眼看不到长城。长城宽度仅约 6-7 米，远低于从近地轨道（约 400 公里）肉眼分辨所需尺度。这一说法最早源于 20 世纪初的误传，从未被航天员证实。",
        "sources": [
            {"title": "杨利伟：在太空看不到长城 - 中国航天", "url": "http://www.cmse.gov.cn/",
             "domain": "cmse.gov.cn", "published_at": "2023-10-01", "credibility": "A",
             "credibility_score": 94, "source_type": "knowledge", "org_type": "政府机构",
             "snippet": "航天员杨利伟明确表示，在太空肉眼看不到长城。「太空可见长城」是流传已久的误传。"},
        ],
        "caveat": "",
    },
    {
        "id": "K023", "name": "每天要喝8杯水",
        "patterns": [r"(每天|每日).{0,8}(8杯|八杯)水", r"8杯水.{0,10}(每天|健康)"],
        "consensus": "部分属实（表述不严谨）", "level": "partly_true",
        "explain": "「每天 8 杯水」并非严格的科学结论。中国居民膳食指南建议成年男性每日饮水约 1700ml、女性约 1500ml，且需根据气候、运动量、体质调整。此外，食物（水果、蔬菜、汤）也提供水分，不必机械按杯数计算。",
        "sources": [
            {"title": "中国居民膳食指南（2022）- 中国营养学会", "url": "https://www.cnsoc.org/",
             "domain": "cnsoc.org", "published_at": "2022-04-26", "credibility": "A",
             "credibility_score": 94, "source_type": "knowledge", "org_type": "学会",
             "snippet": "成年男性每日饮水约1700ml，女性约1500ml，具体需根据气候、体力活动等调整。"},
        ],
        "caveat": "饮水量应因人而异，「8 杯」只是通俗近似说法。",
    },
    {
        "id": "K024", "name": "左脑逻辑右脑创造",
        "patterns": [r"(左脑|右脑).{0,12}(逻辑|创造|艺术|理性)"],
        "consensus": "不实（流行误区）", "level": "false",
        "explain": "「左脑理性、右脑感性」是过度简化的流行说法。脑科学研究表明，复杂认知功能（语言、逻辑、创造）都需要左右脑协同完成，虽然存在一定的功能偏侧化（如语言中枢多在左脑），但不存在「左脑人」「右脑人」的划分。",
        "sources": [
            {"title": "左右脑分工理论是误区 - 科普中国", "url": "https://www.kepuchina.cn/",
             "domain": "kepuchina.cn", "published_at": "2023-09-05", "credibility": "A",
             "credibility_score": 91, "source_type": "knowledge", "org_type": "科普",
             "snippet": "脑科学研究表明，复杂认知任务需要左右脑协同，不存在「左脑型」「右脑型」人格划分。"},
        ],
        "caveat": "",
    },
    {
        "id": "K025", "name": "空腹不能吃香蕉",
        "patterns": [r"空腹.{0,10}(香蕉|不能吃|不宜)"],
        "consensus": "不实（常见误区）", "level": "false",
        "explain": "健康人群空腹吃香蕉并无危害。香蕉含镁、钾，但正常食用量（1-2 根）远不足以引起血镁血钾异常。仅肾功能不全者需注意钾摄入。所谓「空腹吃香蕉伤心脏」缺乏临床依据。",
        "sources": [
            {"title": "空腹不能吃香蕉？误区 - 科普中国", "url": "https://www.kepuchina.cn/",
             "domain": "kepuchina.cn", "published_at": "2023-06-12", "credibility": "A",
             "credibility_score": 90, "source_type": "knowledge", "org_type": "科普",
             "snippet": "健康人群空腹适量吃香蕉不会造成血钾血镁异常，该说法缺乏科学依据。"},
        ],
        "caveat": "肾功能不全者需遵医嘱控制钾摄入。",
    },
    {
        "id": "K026", "name": "喝咖啡致癌",
        "patterns": [r"咖啡.{0,10}(致癌|癌症|有害)"],
        "consensus": "不实", "level": "false",
        "explain": "2016 年世界卫生组织下属国际癌症研究机构（IARC）将咖啡从「可能致癌物」名单中移除，明确表示没有足够证据证明咖啡致癌。适量饮用咖啡（每日 3-4 杯）与多种健康获益相关。",
        "sources": [
            {"title": "IARC 咖啡致癌性评估 - 世界卫生组织", "url": "https://www.iarc.who.int/",
             "domain": "iarc.who.int", "published_at": "2016-06-15", "credibility": "A",
             "credibility_score": 95, "source_type": "knowledge", "org_type": "国际组织",
             "snippet": "IARC removed coffee from the list of possibly carcinogenic substances, finding inadequate evidence for carcinogenicity in humans."},
        ],
        "caveat": "过量饮用（尤其高温饮品）仍需注意。",
    },
    {
        "id": "K027", "name": "隔夜菜致癌",
        "patterns": [r"隔夜(菜|饭|食物).{0,10}(致癌|亚硝酸盐|不能吃)"],
        "consensus": "基本不实（需正确储存）", "level": "false",
        "explain": "隔夜菜在冷藏条件下亚硝酸盐含量远低于安全限值。实验显示，冷藏 24 小时的常见菜肴亚硝酸盐含量仍在安全范围内。风险主要来自常温长时间存放导致的细菌繁殖，而非亚硝酸盐致癌。",
        "sources": [
            {"title": "隔夜菜亚硝酸盐含量实验 - 科普中国", "url": "https://www.kepuchina.cn/",
             "domain": "kepuchina.cn", "published_at": "2023-11-08", "credibility": "A",
             "credibility_score": 90, "source_type": "knowledge", "org_type": "科普",
             "snippet": "冷藏条件下的隔夜菜亚硝酸盐含量远低于国家安全标准，正常食用无致癌风险。"},
        ],
        "caveat": "需冷藏保存并充分加热，常温久放的菜不建议食用。",
    },
    {
        "id": "K028", "name": "酸性体质致病",
        "patterns": [r"酸性体质", r"碱性体质", r"体质.{0,6}(酸性|碱性)"],
        "consensus": "不实（伪科学）", "level": "false",
        "explain": "「酸性体质」「碱性体质」是伪科学概念。人体血液 pH 值由呼吸、肾脏等系统精密调节，稳定在 7.35-7.45 之间，不会因饮食改变。该概念常被用于推销「碱性水」「排酸」类产品。",
        "sources": [
            {"title": "「酸性体质」是伪科学 - 科普中国", "url": "https://www.kepuchina.cn/",
             "domain": "kepuchina.cn", "published_at": "2023-04-18", "credibility": "A",
             "credibility_score": 92, "source_type": "knowledge", "org_type": "科普",
             "snippet": "人体血液pH值稳定在7.35-7.45，由自身调节系统精密控制，不存在「酸性体质」之说。"},
        ],
        "caveat": "",
    },
    {
        "id": "K029", "name": "O型血招蚊子",
        "patterns": [r"(O型|血型).{0,10}(蚊子|招蚊)"],
        "consensus": "证据不足", "level": "uncertain",
        "explain": "目前研究认为血型对蚊子吸引力影响很小。蚊子主要受二氧化碳浓度、体温、汗液中的乳酸和皮肤微生物影响。部分研究显示 O 型血略受偏好，但结论不一致，不足以作为定论。",
        "sources": [
            {"title": "蚊子偏好与血型关系研究 - 科普中国", "url": "https://www.kepuchina.cn/",
             "domain": "kepuchina.cn", "published_at": "2023-07-25", "credibility": "A",
             "credibility_score": 88, "source_type": "knowledge", "org_type": "科普",
             "snippet": "蚊子主要受二氧化碳、体温和汗液成分吸引，血型影响证据不足且研究结论不一致。"},
        ],
        "caveat": "相关研究结论尚不一致，不宜作为定论。",
    },
    {
        "id": "K030", "name": "味精有害健康",
        "patterns": [r"味精.{0,10}(有害|致癌|不能吃|伤)"],
        "consensus": "不实", "level": "false",
        "explain": "味精主要成分谷氨酸钠，是国际公认的安全食品添加剂。联合国粮农组织/世卫组织食品添加剂联合专家委员会（JECFA）未设定其每日允许摄入量限制。所谓「中餐馆综合征」缺乏可靠证据。",
        "sources": [
            {"title": "味精安全性评估 - 世界卫生组织", "url": "https://www.who.int/",
             "domain": "who.int", "published_at": "2022-01-20", "credibility": "A",
             "credibility_score": 93, "source_type": "knowledge", "org_type": "国际组织",
             "snippet": "谷氨酸钠被JECFA评估为安全食品添加剂，未设定每日允许摄入量限制。"},
        ],
        "caveat": "高温长时间加热会损失鲜味，但不产生危害。",
    },
    {
        "id": "K031", "name": "WiFi辐射有害",
        "patterns": [r"(WiFi|WIFI|路由器|无线).{0,12}(辐射|有害|致癌|健康)"],
        "consensus": "不实", "level": "false",
        "explain": "WiFi 属于非电离辐射，功率极低（通常 0.1 瓦以下），远低于国际非电离辐射防护委员会（ICNIRP）安全限值。世界卫生组织明确表示，目前没有证据表明低强度射频电磁场会对健康造成不良影响。",
        "sources": [
            {"title": "电磁场与公共卫生 - 世界卫生组织", "url": "https://www.who.int/",
             "domain": "who.int", "published_at": "2022-08-01", "credibility": "A",
             "credibility_score": 94, "source_type": "knowledge", "org_type": "国际组织",
             "snippet": "目前没有证据表明低强度射频电磁场暴露会对健康产生不良影响。"},
        ],
        "caveat": "",
    },
    {
        "id": "K032", "name": "转基因食品致癌",
        "patterns": [r"转基因.{0,10}(致癌|有害|不安全)"],
        "consensus": "不实（主流科学共识）", "level": "false",
        "explain": "世界卫生组织、美国国家科学院、欧盟委员会等机构的多项综述均认为，已批准上市的转基因食品与传统食品同样安全。所谓「转基因致癌」源于一项已被撤稿且方法学受质疑的研究。",
        "sources": [
            {"title": "转基因食品问答 - 世界卫生组织", "url": "https://www.who.int/",
             "domain": "who.int", "published_at": "2023-03-15", "credibility": "A",
             "credibility_score": 94, "source_type": "knowledge", "org_type": "国际组织",
             "snippet": "已批准上市的转基因食品经过安全评估，可安全食用。"},
        ],
        "caveat": "",
    },
    {
        "id": "K033", "name": "微波炉致癌",
        "patterns": [r"微波炉.{0,12}(致癌|辐射|有害|营养)"],
        "consensus": "不实", "level": "false",
        "explain": "微波炉加热属于非电离辐射，不会使食物产生放射性。微波加热对营养的影响与其他加热方式相当，某些情况下（如短时加热蔬菜）营养保留更好。",
        "sources": [
            {"title": "微波炉安全性 - 科普中国", "url": "https://www.kepuchina.cn/",
             "domain": "kepuchina.cn", "published_at": "2023-05-20", "credibility": "A",
             "credibility_score": 90, "source_type": "knowledge", "org_type": "科普",
             "snippet": "微波炉使用非电离辐射，不会使食物产生放射性，正常使用安全。"},
        ],
        "caveat": "",
    },
    {
        "id": "K034", "name": "手机整夜充电损坏电池",
        "patterns": [r"手机.{0,12}(整夜|过夜|长时间).{0,10}(充电|损坏)", r"整夜充电.{0,10}(电池|损坏)"],
        "consensus": "不实", "level": "false",
        "explain": "现代智能手机采用锂电池并配有电源管理芯片，充满后会自动停止充电（涓流保护）。整夜充电不会「过充」损坏电池。真正影响电池寿命的是高温、深度放电和长期满电存放。",
        "sources": [
            {"title": "锂电池充电管理机制 - 中国电子技术标准化研究院", "url": "http://www.cesi.cn/",
             "domain": "cesi.cn", "published_at": "2023-09-10", "credibility": "A",
             "credibility_score": 92, "source_type": "knowledge", "org_type": "科研机构",
             "snippet": "智能手机锂电池配有充电管理芯片，充满后自动停止充电，整夜充电不会造成过充损坏。"},
        ],
        "caveat": "高温环境下充电会加速电池老化。",
    },
]
def match_knowledge(text: str) -> dict | None:
    """匹配通识知识库，命中返回条目（含共识说明与来源）。"""
    norm = re.sub(r"\s+", "", text or "")
    for item in _KNOWLEDGE_BASE:
        for pat in item["patterns"]:
            if re.search(pat, norm):
                return item
    return None
def knowledge_sources(item: dict) -> list[dict]:
    """取出知识条目的来源列表（深拷贝）。"""
    return [dict(s) for s in item.get("sources", [])]