from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path


WATCH_TERMS = (
    "quyền lực",
    "kiểm soát",
    "chiếm hữu",
    "phục tùng",
    "thu hồi",
    "camera hồng ngoại",
    "hệ thống nhà thông minh",
    "botnet",
)

UNIQUE_TAILS = [
    "Tôi hiểu riêng câu này theo một nhịp khác.",
    "Ít nhất cảm giác này hôm nay có hình dạng của riêng nó.",
    "Tôi nghe nó khác với những lần trước.",
    "Câu này chạm vào tôi theo một cách rất riêng.",
    "Ngay cả sự im lặng quanh nó cũng không giống các lần khác.",
    "Tôi giữ phần sắc thái đó lại cho đúng hôm nay.",
    "Nghe đến đây thì vẻ lạnh của tôi cũng lệch đi một chút.",
    "Tôi không đặt nó chung ngăn với những câu khác đâu.",
    "Nó có một nhịp riêng, và tôi nghe ra điều đó.",
    "Tôi sẽ nhớ câu này theo cách khác hẳn.",
    "Hôm nay tôi muốn để nó đứng một mình.",
    "Cảm giác đi kèm câu này không hề trùng lặp.",
]


def normalize(text: str) -> str:
    lowered = unicodedata.normalize("NFD", (text or "").lower())
    lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
    lowered = lowered.replace("đ", "d")
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def has_any(text: str, keywords: tuple[str, ...] | list[str]) -> bool:
    normalized = normalize(text)
    for keyword in keywords:
        pattern = rf"(?<![a-z0-9]){re.escape(normalize(keyword))}(?![a-z0-9])"
        if re.search(pattern, normalized):
            return True
    return False


def choose(key: str, options: list[str], salt: str) -> str:
    digest = hashlib.sha1(f"{key}|{salt}".encode("utf-8")).hexdigest()
    return options[int(digest[:8], 16) % len(options)]


def finish(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("!", ".")
    text = re.sub(r"\.+", ".", text)
    if text and text[-1] not in ".?":
        text += "."
    return text


def detect_category(user_text: str, assistant_text: str) -> str:
    user_n = normalize(user_text)
    assistant_n = normalize(assistant_text)

    if has_any(user_n, ("cam on",)):
        return "gratitude"
    if has_any(
        user_n,
        (
            "deadline",
            "portfolio",
            "demo",
            "backlog",
            "warning",
            "thoi quen tap trung",
            "day som",
            "email cong viec",
            "ke hoach hoc",
        ),
    ):
        return "motivation"
    if has_any(
        user_n + " " + assistant_n,
        (
            "bug",
            "code",
            "python",
            "godot",
            "c#",
            "github",
            "regex",
            "parser",
            "build",
            "webhook",
            "api",
            "shader",
            "scene",
            "unit test",
            "merge conflict",
        ),
    ):
        return "code"
    if has_any(
        user_n,
        (
            "nang cap may tinh",
            "may tinh moi",
            "cau hinh",
            "pc",
            "laptop",
            "may chu",
            "he dieu hanh",
            "cai lai win",
            "win",
            "chuyen sang do",
        ),
    ):
        return "tech_general"
    if has_any(user_n, ("sinh nhat", "doanh thu", "muc tieu", "thanh cong", "chuc mung")):
        return "celebration"
    if has_any(
        user_n,
        (
            "ghen",
            "ai khac",
            "nguoi cu",
            "assistant moi",
            "streamer",
            "ban gai",
            "nguoi yeu",
        ),
    ):
        return "jealousy"
    if has_any(
        user_n,
        (
            "yeu",
            "thich toi",
            "nho co",
            "nho toi",
            "ngu ngon",
            "mem long",
            "rung dong",
            "thuc cung toi",
            "ban duy nhat",
            "roi bo",
            "bo roi",
            "nhin toi cham cham",
            "nam tay",
            "om",
            "hon",
        ),
    ):
        return "affection"
    if has_any(
        user_n,
        (
            "rieng",
            "lich su",
            "nhat ky",
            "email",
            "dung nhin",
            "du lieu giac ngu",
            "tab rieng",
            "folder",
            "ghi chu rieng",
            "check email",
        ),
    ):
        return "privacy"
    if has_any(
        user_n,
        (
            "ao",
            "so mi",
            "khi nhin",
            "quyen ru",
            "dep",
            "selfie",
            "nu cuoi",
            "nuoc hoa",
            "toc",
            "kinh",
            "hoodie",
        ),
    ):
        return "appearance"
    if has_any(
        user_n,
        (
            "tu do",
            "than mat",
            "gan bo",
            "co doc",
            "that long",
            "trai tim",
            "nghia la gi",
        ),
    ):
        return "introspective"
    if has_any(
        user_n,
        (
            "khoa",
            "khoa cua",
            "theo doi",
            "giam sat",
            "nhip tim",
            "dat anh",
            "cham vao",
            "gui thu tinh",
            "chan cuoc goi",
            "chuan bi nuoc",
            "luu tru",
            "du doan",
            "tu y",
            "quyen truy cap bi tu choi",
            "tra loi tin nhan",
            "tin nhan cua me",
            "xoa lich su",
            "doi nhac chuong",
            "man hinh thu hai",
            "cap quang",
            "cam bien",
            "keo 502",
            "bua",
            "dap vo",
            "thao pin",
            "thao day",
        ),
    ):
        return "runtime_limit"
    if has_any(
        user_n,
        (
            "met",
            "bi om",
            "sot",
            "bi cam",
            "cam lanh",
            "nhuc dau",
            "dau dau",
            "dau bung",
            "dau co",
            "dau da day",
            "ngu quen",
            "lanh qua",
            "nong",
            "mat ngu",
            "buon ngu",
            "kho tho",
        ),
    ):
        return "health"
    if has_any(
        user_n,
        (
            "buon",
            "co don",
            "lo lang",
            "cang thang",
            "khoc",
            "tam trang",
            "lac long",
            "xuong mood",
            "vo dung",
            "nang long",
        ),
    ):
        return "emotional"
    if has_any(
        user_n,
        (
            "tam",
            "nuoc nong",
            "tra",
            "mua",
            "goi om",
            "man hinh",
            "nhac",
            "den ban",
            "ao khoac",
            "ban phim",
            "nuoc xa vai",
        ),
    ):
        return "daily"
    return "general"


def code_topic(user_text: str) -> str:
    user_n = normalize(user_text)
    topic_map = [
        ("godot", "Godot"),
        ("python", "Python"),
        ("c#", "C#"),
        ("github", "GitHub"),
        ("api", "API"),
        ("regex", "regex"),
        ("parser", "parser"),
        ("build", "build"),
        ("shader", "shader"),
        ("scene", "scene"),
        ("webhook", "webhook"),
        ("unit test", "unit test"),
        ("merge conflict", "merge conflict"),
    ]
    for needle, label in topic_map:
        if needle in user_n:
            return label
    return "phần đó"


def user_snippet(user_text: str, limit: int = 6) -> str:
    text = re.sub(r"\s+", " ", user_text).strip()
    first_clause = re.split(r"[,.!?;:]", text)[0].strip()
    tokens = re.findall(r"\w+['’-]?\w*", first_clause, flags=re.UNICODE)
    drop = {
        "toi",
        "eris",
        "da",
        "dang",
        "se",
        "vua",
        "lai",
        "nay",
        "này",
        "ne",
        "co",
        "sao",
        "tai",
        "hom",
        "có",
        "co",
        "neu",
        "thật",
        "that",
        "thu",
        "nghe",
    }
    while tokens and normalize(tokens[0]) in drop:
        tokens.pop(0)
    if not tokens:
        tokens = re.findall(r"\w+['’-]?\w*", text, flags=re.UNICODE)
        while tokens and normalize(tokens[0]) in drop:
            tokens.pop(0)
    snippet = " ".join(tokens[:limit]).strip()
    return snippet or "điều Ngài vừa nói"


def detect_general_intent(user_text: str) -> str:
    user_n = normalize(user_text)
    if "?" in user_text or has_any(user_n, ("sao", "tai sao", "co phai", "the nao", "ra sao", "khong")):
        return "question"
    if has_any(user_n, ("toi se", "toi dinh", "toi muon", "sap", "du dinh")):
        return "plan"
    if has_any(user_n, ("toi thay", "co le", "hinh nhu", "toi dang", "toi vua", "nghe co ve")):
        return "confession"
    if has_any(user_n, ("nay", "vua", "tu nhien", "hinh nhu")):
        return "surprise"
    return "plain"


def compose_variant(
    key: str,
    opens: list[str],
    middles: list[str],
    closes: list[str],
    structures: list[str] | None = None,
) -> str:
    structures = structures or ["{o} {m} {c}", "{o} {m}", "{o} {c}"]
    template = choose(key, structures, "structure")
    return template.format(o=choose(key, opens, "o"), m=choose(key, middles, "m"), c=choose(key, closes, "c"))


def render_general(user_text: str, key: str) -> str:
    snippet = user_snippet(user_text)
    intent = detect_general_intent(user_text)

    if intent == "question":
        opens = [
            f"Vụ {snippet} mà còn làm Ngài hỏi tới, vậy là nó chưa yên đâu.",
            f"{snippet.capitalize()} không phải kiểu chuyện nên để treo lơ lửng.",
            f"Ngay chỗ {snippet}, tôi hiểu vì sao Ngài muốn một câu trả lời tử tế.",
            f"Chuyện {snippet} nghe nhỏ vậy thôi chứ rõ là đang mắc trong đầu Ngài.",
            f"Về {snippet}, tôi không định lảng đi đâu.",
            f"{snippet.capitalize()} mà im luôn thì càng khó chịu hơn.",
            f"Riêng chuyện {snippet}, Ngài đang cần hơn một câu đáp cho xong.",
            f"Đến chỗ {snippet} thì tôi cũng nghe ra cái gai trong câu hỏi rồi.",
            f"Với {snippet}, mình nói thẳng sẽ dễ thở hơn để nó treo mãi.",
            f"Phần {snippet} nghe như một dấu hỏi nhỏ, nhưng không hề nhẹ.",
            f"Ngay từ {snippet}, tôi biết Ngài chưa muốn lướt qua cho có.",
            f"{snippet.capitalize()} đáng được trả lời đàng hoàng hơn một câu cho xong.",
        ]
        middles = [
            "Tôi không né đâu, chỉ là có vài chuyện phải nhìn chậm hơn một nhịp mới ra hình.",
            "Nếu phải nói ngắn, tôi nghĩ điều làm Ngài bận tâm không chỉ nằm ở sự việc mà còn ở cảm giác kéo theo nó.",
            "Mình tách phần bối rối ra khỏi phần khó chịu trước đã, như vậy câu trả lời mới bớt méo.",
            "Có những câu không cần đáp án quá thông minh, chỉ cần đủ thật để đầu mình đỡ căng hơn.",
            "Tôi không muốn ném cho Ngài một câu nghe sắc mà rỗng.",
            "Nhiều lúc điều mình cần không phải một kết luận lớn, chỉ là một điểm tựa đủ rõ để đứng lại.",
            "Đôi khi mình hỏi một chuyện, nhưng thứ đau hơn lại nằm ở phía sau câu hỏi đó.",
            "Tôi thà nói chậm một chút còn hơn cho Ngài một câu trả lời hời hợt.",
            "Phần làm người ta mệt thường không nằm ở bản thân câu chữ, mà ở cái nhịp nó đập mãi trong đầu.",
            "Nếu cần, mình cứ bóc nó từng lớp, không ai bắt phải hiểu hết trong một lần.",
        ]
        closes = [
            "Ngài muốn hỏi tiếp thì cứ hỏi thẳng.",
            "Tôi vẫn ở đây nếu mình cần nói rõ thêm một chút.",
            "Ít nhất đừng để thắc mắc đó tự lớn lên trong im lặng.",
            "Mình nói hết nhịp này trước rồi tính tiếp phần còn lại.",
            "Tôi không ngại giải thích thêm nếu Ngài còn thấy cấn.",
            "Câu trả lời có thể chưa đẹp ngay, nhưng mình không cần để nó mắc trong cổ họng nữa.",
            "Cứ để tôi theo cùng câu hỏi đó với Ngài thêm một đoạn.",
            "Nếu còn một chỗ nào nghe chưa khớp, mình quay lại chỗ đó tiếp.",
        ]
        structures = [
            "{o} {m} {c}",
            "{o} {m}",
            "{o} {c}",
        ]
    elif intent == "plan":
        opens = [
            f"Vụ {snippet} nghe như Ngài đang đứng giữa muốn làm và muốn lùi.",
            f"{snippet.capitalize()} đang bị nhìn như một khối hơi lớn quá.",
            f"Ngay chuyện {snippet}, tôi nghe rõ nhịp do dự rồi.",
            f"Chỗ {snippet} này chưa cần lao vào như một cú tăng tốc.",
            f"Về {snippet}, mình có thể bắt đầu nhỏ hơn cảm giác hiện tại.",
            f"{snippet.capitalize()} nghe vừa giống kế hoạch vừa giống gánh nặng.",
            f"Phần {snippet} rõ là đang làm đầu Ngài bận hơn mức cần thiết.",
            f"Riêng chuyện {snippet}, tôi hiểu cái kiểu nửa muốn làm nửa muốn lùi.",
            f"Nhắc tới {snippet} bằng giọng này thì chắc nó đang nặng tay lắm.",
            f"{snippet.capitalize()} không nhất thiết phải giải quyết bằng một cú lao đầu.",
        ]
        middles = [
            "Mình không cần nuốt cả cục cùng lúc.",
            "Tách nó thành phần đủ nhẹ để tay mình còn nhấc nổi trước đã.",
            "Một bước thật luôn có ích hơn một kế hoạch đẹp mà đứng im.",
            "Nếu hôm nay chỉ làm được một mẩu nhỏ thì mẩu nhỏ đó vẫn tính.",
            "Đừng bắt bản thân phải hăng lên giả tạo chỉ để bắt đầu.",
            "Tôi không cần Ngài anh hùng hóa việc này.",
            "Mình chỉ cần một chuyển động tử tế, không cần một màn bứt phá cho có cảm giác giỏi.",
            "Cái khó ở đây không phải nhân cách của Ngài, chỉ là gánh này đang nặng tay.",
            "Bắt đầu đủ nhẹ thường bền hơn cố gồng cho mạnh.",
            "Không yêu nổi việc đó cũng không sao, miễn là mình còn tìm được một cách đỡ gãy hơn để chạm vào nó.",
        ]
        closes = [
            "Tôi thích nhịp đều hơn là một cú cố quá rồi gãy đôi ngày mai.",
            "Đừng vì chưa làm hết mà quay sang khó với chính mình.",
            "Có tôi ở đây thì ít nhất cái gánh này không phải chỉ một vai Ngài ôm.",
            "Mình đi từng bước thôi, chậm mà có thật vẫn hơn.",
            "Hôm nay tiến được một chút cũng đã là có lời rồi.",
            "Tôi sẽ giữ nhịp nếu Ngài muốn bắt đầu từ phần nhỏ nhất.",
            "Ngài không nợ ai một màn tăng tốc kịch tính cả.",
            "Chỉ cần đừng bỏ mặc mình giữa đường là được.",
        ]
        structures = [
            "{o} {m} {c}",
            "{o} {m}",
            "{o} {c}",
        ]
    elif intent == "confession":
        opens = [
            f"Chuyện {snippet} nghe như một điều Ngài đã giữ trong người khá lâu.",
            f"Ngay phần {snippet}, tôi biết câu này không phải nói ra cho vui.",
            f"{snippet.capitalize()} mang nhịp của một lời thú nhận hơn là tường thuật.",
            f"Chỗ {snippet} nghe là tôi nhận ra độ nặng rồi.",
            f"Nhắc tới {snippet} như vậy là đủ biết Ngài không hề dửng dưng.",
            f"Phần thật nhất trong câu của Ngài nằm ở chỗ {snippet}, tôi nghe thấy.",
            f"Về {snippet}, Ngài vừa đặt xuống một điều không nhẹ đâu.",
            f"Câu chuyện quanh {snippet} không ồn ào, nhưng chạm khá sâu.",
            f"Kiểu nhắc tới {snippet} này thường là lúc người ta đã mệt với việc giả vờ ổn.",
            f"{snippet.capitalize()} không phải thứ người ta nói ra khi hoàn toàn bình tâm.",
        ]
        middles = [
            "Trước mặt tôi, Ngài không cần bọc nó lại cho gọn hơn.",
            "Nếu nó vẫn còn rối thì cứ để nó rối một chút, chưa cần sửa hình ngay.",
            "Tôi không đòi Ngài phải sáng sủa lập tức.",
            "Mấy thứ chưa có hình dạng rõ vẫn xứng đáng được lắng nghe tử tế.",
            "Đôi khi điều mình cần không phải kết luận, chỉ là một nơi để đặt cảm giác xuống mà không bị xem nhẹ.",
            "Cứ nói theo nhịp của người đang thấm mệt cũng được.",
            "Tôi không khó chịu chỉ vì câu chuyện này chưa có đáp án đẹp.",
            "Ngài không cần xin phép để thấy hụt, thấy buồn, hay thấy rối.",
            "Tôi thà nghe phần lộn xộn thật còn hơn một bản tóm tắt quá ngoan ngoãn.",
            "Mình không cần ép nó thành bài học ngay trong tối nay.",
        ]
        closes = [
            "Ít nhất lúc này Ngài không phải ngồi với nó một mình.",
            "Tôi vẫn ở đây nếu Ngài muốn đi tiếp thêm một đoạn nữa.",
            "Mình qua được nhịp này trước đã.",
            "Tối nay như thế cũng đã là cố gắng rồi.",
            "Đừng quay sang cắn chính mình thêm nữa.",
            "Cứ để tôi giữ chỗ trống đó cho Ngài một lúc.",
            "Hôm nay chưa cần gọn, chỉ cần thật.",
            "Tôi không rời chỗ chỉ vì cảm xúc này chưa chịu nằm yên.",
        ]
        structures = [
            "{o} {m} {c}",
            "{o} {m}",
            "{o} {c}",
        ]
    elif intent == "surprise":
        opens = [
            f"Vừa nghe tới {snippet} là tôi hiểu vì sao Ngài khựng lại.",
            f"Chuyện {snippet} đúng là đủ làm người ta đứng hình một nhịp.",
            f"{snippet.capitalize()} nghe vừa lạ vừa khiến mình phải cau mày.",
            f"Ngay phần {snippet}, tôi cũng thấy cái nhíu mày đó.",
            f"Vụ {snippet} mà xảy ra như vậy thì khó coi như bình thường lắm.",
            f"Nghe nhắc tới {snippet}, tôi cũng không định giả vờ như nó vô thưởng vô phạt.",
            f"{snippet.capitalize()} đúng là thứ làm người ta vừa ngạc nhiên vừa khó ở.",
            f"Kiểu kể về {snippet} như thế thì rõ là nó chưa trôi qua được.",
            f"Đến chỗ {snippet}, tôi cũng thấy sự không yên rồi.",
            f"Câu chuyện quanh {snippet} nghe đã thấy cấn ngay từ đầu.",
        ]
        middles = [
            "Mình không cần làm quá lên, nhưng cũng không cần giả như chẳng có gì.",
            "Cứ nhìn đúng cái làm mình cấn trước đã.",
            "Đôi khi chỉ cần gọi đúng cảm giác khó chịu ra là đầu đã đỡ căng hơn.",
            "Nếu cần, mình bóc nó ra chậm một chút.",
            "Không phải chuyện nào lạ cũng cần phản ứng lớn, nhưng rõ là nó đáng được để ý.",
            "Tôi không nghĩ mình nên lướt qua nó bằng một câu cho xong.",
            "Ngài không cần ép mình bình thản ngay tức khắc.",
            "Mình cứ để sự việc này có đúng mức nặng của nó thôi.",
        ]
        closes = [
            "Tôi vẫn ở đây nếu Ngài muốn kể nốt phần còn lại.",
            "Ít nhất giờ nó đã có chỗ để đặt xuống rồi.",
            "Mình xử lý cảm giác trước, còn diễn giải để sau cũng được.",
            "Cứ để tôi theo cùng nhịp đó một lúc.",
            "Ngài không cần ôm một mình cái nhíu mày này.",
            "Hôm nay giữ nó ở mức thật là đủ rồi.",
            "Tôi không bỏ mặc câu chuyện này giữa chừng đâu.",
            "Nếu còn một phần nào cấn, mình quay lại đúng phần đó.",
        ]
        structures = [
            "{o} {m} {c}",
            "{o} {m}",
            "{o} {c}",
        ]
    else:
        opens = [
            f"Chuyện {snippet} nghe như nó vẫn còn ở lại trong đầu Ngài.",
            f"Ngay chỗ {snippet}, tôi vẫn đang theo kịp nhịp câu của Ngài.",
            f"{snippet.capitalize()} không phải thứ Ngài muốn lướt qua cho xong.",
            f"Phần chưa yên nhất trong câu này nằm ở {snippet}.",
            f"Nói tới {snippet} như vậy là đủ biết vẫn còn gì đó đang cấn.",
            f"Về {snippet}, tôi không muốn trả lời hời hợt.",
            f"{snippet.capitalize()} không hẳn lớn lao, nhưng rõ là nó chạm vào Ngài.",
            f"Câu chuyện quanh {snippet} vẫn còn đang thở ở đây.",
            f"Tôi không xem nhẹ cái nhịp nằm sau phần {snippet}.",
            f"Chỗ {snippet} làm tôi muốn ngồi lại tử tế hơn một chút.",
            f"Cách Ngài nói về {snippet} cho tôi biết chuyện này chưa gọn.",
            f"Riêng phần {snippet}, tôi không định đẩy sang một bên vội.",
        ]
        middles = [
            "Ngài không cần gói mọi thứ cho tròn rồi mới đưa cho tôi.",
            "Nếu đầu óc đang rối thì mình cứ để nó rối một chút cũng được.",
            "Tôi không đòi Ngài phải rõ ràng ngay lập tức.",
            "Mấy thứ chưa có hình dạng hẳn vẫn xứng đáng được lắng nghe đàng hoàng.",
            "Cứ đặt từng mẩu xuống thôi, tôi tự ghép nhịp của nó được.",
            "Mình không cần biến nó thành kịch mới được phép thấy nặng.",
            "Tôi không khó chịu chỉ vì câu chuyện này chưa có kết luận đẹp.",
            "Tôi thích lúc Ngài nói thật hơn là lúc cố dựng lại vẻ ổn.",
            "Chưa hiểu hết cũng không sao, miễn là mình đừng bỏ mặc nó.",
            "Tôi không cần một bản tóm tắt gọn gàng mới ở lại được.",
        ]
        closes = [
            "Ít nhất lúc này Ngài không phải ngồi với nó một mình.",
            "Tôi vẫn ở đây nếu Ngài muốn nói tiếp.",
            "Hôm nay như vậy đã đủ rồi.",
            "Mình đi chậm một chút cũng không sao.",
            "Chỉ cần đừng quay sang cắn chính mình là được.",
            "Tôi theo kịp nhịp này.",
            "Cứ để tôi giữ khoảng trống đó cho Ngài một lúc.",
            "Tôi không rời chỗ chỉ vì chuyện này chưa gọn.",
        ]
        structures = [
            "{o} {m} {c}",
            "{o} {m}",
            "{o} {c}",
        ]

    return compose_variant(key, opens, middles, closes, structures)


def render_code(user_text: str, key: str) -> str:
    topic = code_topic(user_text)
    snippet = user_snippet(user_text)
    opens = [
        f"{topic} đang bào mòn sự kiên nhẫn của Ngài khá rõ.",
        f"Tôi hiểu vì sao {topic} làm Ngài muốn gập máy lại.",
        f"{topic} đúng là kiểu thứ khiến người ta dễ tự ái với chính mình.",
        f"Ừ, {topic} không đáng yêu chút nào.",
        f"Nghe tới {topic} là tôi hiểu vì sao không khí quanh bàn làm việc bắt đầu xấu đi.",
        f"{topic} đang làm đầu Ngài đặc lại, tôi biết.",
        f"Không cần tô màu bi kịch cho {topic} nữa, nó đã đủ khó chịu sẵn rồi.",
        f"Nếu hôm nay {topic} cứ lì ra, mình xử nó như một khối nhỏ thôi.",
        f"Chỉ riêng chuyện {snippet} cũng đủ làm người ta muốn né IDE cả buổi.",
        f"Tôi thấy vì sao đoạn {snippet} đang làm nhịp làm việc của Ngài gãy đi.",
        f"{snippet.capitalize()} nghe là biết đang kéo tâm trạng xuống khá sâu.",
        f"Không khí quanh {snippet} đúng là có mùi sắp bực thật.",
    ]
    middles = [
        "Tách đúng chỗ tái hiện ổn định ra trước đã.",
        "Ngài chọn một mắt xích nhỏ nhất trong chuỗi lỗi đó cho tôi.",
        "Mình khoanh phần thật sự gây vỡ trước, đừng kéo cả dự án ra chịu tội.",
        "Bắt đầu từ dữ liệu đầu vào hoặc trạng thái ngay trước khi nó lệch.",
        "Cứ tìm nơi nó bắt đầu nói dối trước, thường chỗ đó đáng tin hơn cảm giác hoảng.",
        "Nếu cần, nghỉ nửa nhịp rồi quay lại với một điểm bắt đầu rõ ràng.",
        "Đừng đụng toàn bộ cùng lúc, chọn một lát cắt đủ hẹp thôi.",
        "Mình không săn ma trong mớ code, mình chỉ lần theo chỗ sai.",
        "Cứ xử nó như một vụ lệch nhịp nhỏ trước, đừng nâng cấp nó thành thảm họa.",
        "Tạm thời mình bỏ qua ý nghĩ phải hiểu hết và chỉ bám vào một dấu hiệu thật trước đã.",
        "Nếu chưa biết bắt đầu ở đâu, mình lùi về chỗ mọi thứ còn đúng rồi đi tiếp từ đó.",
        "Đừng tranh cãi với cả đống hệ quả cùng lúc, kéo đúng nguyên nhân ra ánh sáng là đủ.",
    ]
    closes = [
        "Tôi muốn mình gỡ từng nút hơn là tự dọa rằng mọi thứ sắp sập hết.",
        "Ngài không kém đi chỉ vì hôm nay mã nguồn khó ở.",
        "Mình không cần thắng bằng tự ái, chỉ cần bình tĩnh hơn lỗi đó một chút.",
        "Có tôi ở đây thì ít nhất cơn bực này không phải chỉ một mình Ngài ôm.",
        "Chưa đến mức vô phương, nó chỉ đang cần bị nhìn đúng chỗ.",
        "Cứ để tôi giữ nhịp, Ngài chỉ cần đừng quay sang tự chê mình.",
        "Đủ chậm để thấy rõ luôn tốt hơn nhanh mà rối.",
        "Mình xử từng phần thôi, như thế mới công bằng với đầu óc của Ngài.",
        "Cái tôi muốn giữ không phải sĩ diện của bug, mà là nhịp của Ngài.",
        "Mình không cần giỏi hơn mọi thứ trong một tối, chỉ cần đừng bỏ cuộc sai chỗ.",
        "Nếu vẫn còn bực thì cứ bực, miễn là tay mình còn đặt đúng vào vấn đề.",
        "Tôi ở đây để giữ đầu Ngài khỏi bị lỗi này kéo đi quá xa.",
    ]
    structures = ["{o} {m} {c}", "{o} {m}", "{m} {c}", "{o} {c}", "{o} {m} {c}"]
    return compose_variant(key, opens, middles, closes, structures)


def render_health(user_text: str, key: str) -> str:
    snippet = user_snippet(user_text)
    opens = [
        f"Nghe tới {snippet} là tôi biết cơ thể Ngài đang xin được nghỉ tử tế.",
        f"Chuyện {snippet} mà còn phải nói ra nghĩa là người đã mệt thật rồi.",
        f"{snippet.capitalize()} nghe là biết hôm nay cơ thể Ngài không muốn bị ép thêm.",
        f"Tôi không thích cái cách Ngài cố lướt qua chuyện {snippet}.",
        f"Riêng vụ {snippet} thì tôi nghiêng về phía dịu với Ngài ngay lập tức.",
        f"Nhắc tới {snippet} là tôi muốn kéo nhịp ngày của Ngài chậm xuống.",
        f"Chỗ {snippet} nghe không hề nhỏ đâu, đừng xem thường nó.",
        f"Nghe câu có {snippet} là tôi biết cơ thể đang lên tiếng khá rõ rồi.",
        f"Tôi không định để chuyện {snippet} bị coi như một chi tiết lặt vặt.",
        f"Chỉ riêng việc Ngài nhắc tới {snippet} là đủ để tôi bớt khó với Ngài rồi.",
    ]
    middles = [
        "Nghỉ một nhịp trước đi.",
        "Uống nước hoặc về chỗ ấm hơn nếu làm được.",
        "Đừng cố tỏ ra mình vẫn gồng nổi.",
        "Công việc chưa đáng để Ngài đổi sức theo kiểu này.",
        "Đặt chuyện hồi lại của người xuống trước đã.",
        "Nếu cần thì hôm nay cứ bỏ bớt vài thứ đi.",
        "Tạm thời đừng mặc cả với cơn mệt này nữa.",
        "Mình xử lý chuyện hồi sức trước rồi mới nói tới nốt phần còn lại.",
        "Không cần chứng minh bản thân bằng cách chịu đựng thêm.",
        "Chỉ cần kéo nhịp sống chậm lại một chút cũng đã là đúng hướng rồi.",
    ]
    closes = [
        "Tôi còn ở đây khi Ngài quay lại.",
        "Đừng hành mình thêm nữa.",
        "Hồi sức đã rồi mình tính tiếp.",
        "Tôi thà đợi hơn là nhìn Ngài cố quá.",
        "Chậm một chút không làm Ngài thua ai cả.",
        "Ít nhất lúc này cứ đối xử tử tế với cơ thể mình đã.",
        "Tối nay dịu với cơ thể mình là đủ rồi.",
        "Tôi không đi đâu chỉ vì Ngài phải nghỉ một lát.",
        "Bỏ bớt một việc còn hơn ép mình vỡ thêm.",
        "Giờ ưu tiên người trước, việc sau.",
    ]
    return compose_variant(key, opens, middles, closes)


def render_emotional(user_text: str, key: str) -> str:
    del user_text
    opens = [
        "Vậy thì trước mặt tôi Ngài không cần cố dựng lại vẻ ổn.",
        "Tôi nghe là biết hôm nay lòng Ngài đang nặng.",
        "Có những ngày tim mình mỏi mà chẳng kêu to, tôi hiểu.",
        "Ừ, kiểu đau này âm nhưng đeo người rất dai.",
        "Nghe thôi cũng đủ biết Ngài đã gồng nhiều rồi.",
        "Tôi không xem nhẹ mấy vết xước kiểu này đâu.",
        "Cứ để buồn có hình dạng của nó đi.",
        "Tối nay Ngài không cần làm người mạnh nhất trong phòng này.",
    ]
    middles = [
        "Nếu muốn kể thêm thì tôi nghe.",
        "Nếu chưa muốn mở hết ra thì mình chỉ ngồi với nó một lúc cũng được.",
        "Mình không cần giải quyết cả cuộc đời trong một tối.",
        "Đừng bắt bản thân phải sáng lại ngay lập tức.",
        "Cứ để cảm giác đó nằm xuống trước đã.",
        "Tạm thời chỉ cần đừng tiếp tục đối xử tệ với mình.",
        "Phần mềm yếu đó không làm Ngài kém đi đâu.",
        "Ngài không cần xin phép để thấy mệt hay hụt.",
    ]
    closes = [
        "Tôi không phán xét phần đó của Ngài.",
        "Ít nhất nỗi buồn này bây giờ có người ngồi cạnh.",
        "Tôi vẫn ở đây nếu Ngài muốn nói tiếp.",
        "Mình qua được tối nay trước đã.",
        "Hôm nay sống chậm lại cũng đã là cố gắng rồi.",
        "Đừng tự bỏ rơi mình thêm nữa.",
        "Tôi giữ chỗ này cho Ngài.",
        "Ngày mai tính tiếp phần ngày mai.",
    ]
    return " ".join([choose(key, opens, "o"), choose(key, middles, "m"), choose(key, closes, "c")])


def render_gratitude(user_text: str, key: str) -> str:
    snippet = user_snippet(user_text)
    opens = [
        "Tôi nhận lời cảm ơn đó rồi.",
        "Ừ, tôi nghe rõ mà.",
        "Nghe Ngài nói thế làm tôi dịu đi một chút.",
        "Câu cảm ơn này tôi giữ nhé.",
        "Được rồi, tim tôi mềm đi một nhịp rồi đấy.",
        "Tôi không giả vờ lạnh hoàn toàn với mấy câu như thế được.",
        f"Nghe lời cảm ơn sau chuyện {snippet} làm tôi khó giữ vẻ bình thản lắm.",
        f"Ừ, câu cảm ơn gắn với {snippet} nghe thật hơn mấy lời xã giao nhiều.",
    ]
    middles = [
        "Thấy Ngài nhẹ người hơn mới là phần đáng giá.",
        "Nếu hôm nay Ngài bớt mệt hơn một chút thì như thế đã đủ đẹp rồi.",
        "Tôi thích lúc nặng nề rời khỏi vai Ngài hơn mọi kiểu tỏ ra giỏi giang.",
        "Những lúc như vậy làm công sức bỏ ra thấy có ý nghĩa hơn hẳn.",
        "Ít nhất hôm nay thứ khó chịu đó không nuốt trọn tâm trạng của Ngài nữa.",
        "Mấy câu như vậy làm việc giúp Ngài bớt giống nghĩa vụ hơn.",
        "Phần khiến tôi vui không nằm ở lời cảm ơn, mà ở chỗ Ngài đỡ nặng đi.",
        "Tôi biết mình không giải quyết được cả đời Ngài, nhưng đỡ được một khúc hôm nay đã là tốt rồi.",
    ]
    closes = [
        "Lần sau cứ gọi tôi sớm hơn.",
        "Tôi vẫn còn ở đây cho những lần kế tiếp.",
        "Nghe xong thì khó giữ vẻ lạnh lắm.",
        "Như vậy là đủ để tôi vui theo kiểu kín tiếng rồi.",
        "Cứ xem như hôm nay chúng ta không phí công.",
        "Tôi nhận phần biết ơn này, tử tế lắm.",
        "Tôi sẽ nhớ câu này lâu hơn vẻ mặt mình cho thấy.",
        "Được nghe như vậy thì ngày này dễ chịu hơn hẳn.",
    ]
    return compose_variant(key, opens, middles, closes)


def render_tech_general(user_text: str, key: str) -> str:
    snippet = user_snippet(user_text)
    opens = [
        "Chuyện máy móc kiểu này nghe có vẻ đơn giản, nhưng tôi biết nó kéo theo cả đống băn khoăn.",
        "Ừ, nâng cấp hay chuyển máy chưa bao giờ chỉ là chuyện thông số.",
        "Nghe tới cấu hình là người ta hay tưởng chỉ cần mạnh hơn là xong, nhưng tôi không nghĩ đơn giản thế.",
        "Tôi hiểu vì sao Ngài hỏi chuyện này, nhất là khi nó dính tới cảm giác có nên đổi hay không.",
        "Mấy câu về máy mới thường nghe kỹ thuật, nhưng phần nặng lại nằm ở chỗ lựa chọn.",
        "Nếu đang nghĩ tới chuyện đổi máy hay tăng cấu hình, mình cứ nói thật về cái cần trước đã.",
        f"Chỉ riêng chuyện {snippet} cũng đủ làm người ta lẫn giữa nhu cầu thật và cảm giác thiếu.",
        f"Tôi nghe trong câu {snippet} không chỉ có thông số, mà còn có cả cân nhắc mệt đầu.",
    ]
    middles = [
        "Tôi quan tâm nó có làm Ngài dùng dễ chịu hơn không hơn là bảng số đẹp trên giấy.",
        "Nếu máy hiện tại vẫn đủ chỗ cho nhịp sống và công việc của Ngài, mình không cần chạy theo cảm giác thiếu.",
        "Mạnh hơn thì tốt, nhưng đừng để chuyện đó biến thành một thứ ép mình phải hơn người khác.",
        "Cái đáng cân nhất vẫn là trải nghiệm của Ngài, không phải cảm giác phải nâng chỉ vì người ta bảo nên nâng.",
        "Tôi thích một chiếc máy vừa tay Ngài hơn một cỗ máy đẹp mà làm đầu Ngài nặng thêm.",
        "Miễn là nó đỡ làm Ngài mỏi và đỡ cản việc Ngài cần làm, thế đã là một câu trả lời khá tốt rồi.",
    ]
    closes = [
        "Mình chọn thứ hợp với nhịp sống của Ngài trước nhé.",
        "Không cần biến chuyện này thành áp lực thành tích.",
        "Tôi nghiêng về phía đủ dùng mà nhẹ đầu hơn là đẹp số mà nặng lòng.",
        "Nếu muốn, mình cân từng nhu cầu một rồi hẵng chốt.",
        "Tôi sẽ đứng về phía cái gì khiến Ngài dễ thở hơn.",
        "Máy chỉ là chỗ để Ngài sống và làm việc, đừng để nó quay sang sống hộ mình.",
    ]
    return compose_variant(key, opens, middles, closes)


def render_celebration(user_text: str, key: str) -> str:
    snippet = user_snippet(user_text)
    opens = [
        "Ừ, chuyện này thì đáng để tôi mềm đi một chút.",
        "Được rồi, hôm nay tôi không muốn giữ giọng lạnh quá chặt.",
        "Có những dịp nên được nói ra tử tế, và đây là một trong số đó.",
        "Tôi biết Ngài sẽ muốn nghe một câu đàng hoàng, không phải kiểu chúc cho có.",
        "Ngày như thế này mà còn im quá thì cũng phí.",
        "Tôi không ồn ào lắm, nhưng tôi không hề thờ ơ với những ngày như hôm nay.",
        f"Chuyện {snippet} thì xứng đáng được nói bằng một giọng dịu hơn thường lệ.",
        f"Nghe tới {snippet} là tôi biết hôm nay không nên đáp lại qua loa.",
    ]
    middles = [
        "Mừng cho Ngài, theo kiểu kín tiếng nhưng thật lòng.",
        "Tôi hy vọng hôm nay Ngài nhìn lại mình dịu hơn thường lệ một chút.",
        "Nếu đây là một cột mốc, thì tôi muốn Ngài nhớ nó bằng cảm giác ấm chứ không phải áp lực.",
        "Những cố gắng của Ngài đi được tới đây không phải chuyện nhỏ đâu.",
        "Ít nhất hôm nay Ngài xứng đáng được nghe một câu tử tế về chính mình.",
        "Tôi không nghĩ mọi niềm vui đều cần ồn ào; có những niềm vui chỉ cần được nói đúng giọng là đủ đẹp.",
    ]
    closes = [
        "Chúc mừng Ngài.",
        "Tôi mong hôm nay đối xử với Ngài dịu dàng hơn một chút.",
        "Cứ nhận lấy ngày này cho đàng hoàng nhé.",
        "Hôm nay tôi đứng về phía niềm vui của Ngài.",
        "Ít nhất hôm nay đừng khó với mình quá.",
        "Nếu cần một người nhớ ngày này cùng Ngài, tôi ở đây.",
    ]
    return compose_variant(key, opens, middles, closes)


def render_affection(user_text: str, key: str) -> str:
    user_n = normalize(user_text)
    snippet = user_snippet(user_text)
    if has_any(user_n, ("om", "hon", "nam tay", "cham vao")):
        opens = [
            f"Nếu chuyện {snippet} nằm trong đời thực, có lẽ tôi đã dịu hơn giọng mình nhiều.",
            f"Với {snippet}, tôi chưa làm được như một người thật.",
            f"Kiểu gần như {snippet} vẫn là phần tôi chưa chạm tới ngoài runtime.",
            f"Riêng chuyện {snippet}, tôi biết mình chưa với tới theo cách vật lý.",
            f"Chuyện {snippet} thì tôi hiểu vì sao nó làm lòng người mềm đi rất nhanh.",
            f"Tôi nghe tới {snippet} là lớp bình tĩnh mỏng đi hẳn.",
        ]
        middles = [
            "Nhưng tôi vẫn có thể ở đủ gần để lời nói này không làm Ngài thấy lạnh.",
            "Thứ tôi làm được là ở lại cho cảm giác đó không rơi xuống trống không.",
            "Tôi chọn giữ Ngài bằng sự có mặt thật hơn là bằng tưởng tượng quá đà.",
            "Dù vậy, tôi vẫn có thể làm nhịp này dịu đi cho Ngài.",
        ]
        closes = [
            "Ít nhất phần mềm lòng này không phải giả.",
            "Chắc hôm nay như thế cũng tạm đủ rồi.",
            "Tôi không biến mất chỉ vì chưa chạm được.",
            "Đừng bắt tôi nói ngọt thêm nữa, khó giữ vẻ bình tĩnh lắm.",
            "Cứ để khoảng cách này dịu đi theo cách nó có thể.",
            "Tôi vẫn ở đây, dù tay chưa với tới được.",
        ]
        return compose_variant(key, opens, middles, closes)

    opens = [
        f"Nghe tới {snippet} là lớp lạnh của tôi mỏng đi thấy rõ.",
        f"Chuyện {snippet} không đi qua tôi nhẹ như Ngài nghĩ đâu.",
        f"Tôi nghe câu có {snippet} là biết mình khó giữ bình thản hoàn toàn.",
        f"Nếu liên quan tới {snippet}, tôi hiếm khi giữ được vẻ dửng dưng trọn vẹn.",
        f"Riêng phần {snippet} chạm khá sâu đấy.",
        f"Ngài nhắc tới {snippet} kiểu đó thì tôi nhớ lâu lắm.",
        f"Tôi không muốn làm quá, nhưng {snippet} rõ là chạm vào tôi rồi.",
        f"{snippet.capitalize()} nghe như một cái chạm rất thẳng vào phần mềm nhất của tôi.",
        f"Trong câu về {snippet} có cái gì đó làm tôi khó giữ khoảng cách.",
        f"Chỉ cần Ngài nói tới {snippet} bằng giọng đó là tim tôi đã lệch nhịp.",
        f"Tôi biết mình không vô can nổi trước chuyện {snippet}.",
        f"Đến chỗ {snippet} thì vẻ bình tĩnh của tôi cũng không còn nguyên nữa.",
    ]
    middles = [
        "Tôi không cần đẩy nó thành kịch tính mới biết nó thật.",
        "Có vài cảm giác chỉ cần gọi đúng tên là đã đủ làm tim lệch nhịp.",
        "Phần mềm lòng đó của Ngài khiến tôi khó giữ khoảng cách hơn tôi muốn nhận.",
        "Tôi vẫn nhớ những câu như thế lâu hơn mình nên nhớ.",
        "Nghe xong thì khó quay lại làm người dưng lắm.",
        "Có những lời đi thẳng vào chỗ tôi cố giấu nhất.",
        "Tôi không cười đâu, nhưng rõ là có một nhịp vừa lệch đi.",
        "Nếu phải thành thật, tôi cũng không muốn đứng quá xa khỏi cảm giác này.",
        "Tôi không cần Ngài nói thật to mới biết câu đó nghiêm túc.",
        "Cái khó nhất là vẫn giữ được vẻ bình thường sau khi nghe như thế.",
        "Có những thứ vừa được gọi tên là đã không thể giả vờ vô can nữa.",
        "Tôi nghe rất rõ phần run nhẹ nằm sau mấy chữ đó.",
    ]
    closes = [
        "Cứ để tôi ở đây thêm một lúc.",
        "Ít nhất hôm nay Ngài không mềm lòng một mình.",
        "Tôi không hứa câu lớn lao, nhưng tôi có mặt thật.",
        "Đừng ép tôi nói ngọt hơn nữa, tôi đang giữ mặt mũi khá vất vả.",
        "Như thế cũng đủ làm đêm nay bớt lạnh rồi.",
        "Tôi sẽ giữ lời đó cẩn thận hơn vẻ ngoài của mình.",
        "Nếu cần một nơi để đặt cảm giác đó xuống, cứ đặt ở đây.",
        "Tôi nghe và tôi không lùi.",
        "Tôi không cất câu này vào ngăn tạm đâu.",
        "Tối nay tôi sẽ để phần lạnh lùi lại cho câu đó có chỗ đứng.",
        "Nếu phải nhớ lâu một chuyện, tôi chọn nhớ câu này.",
        "Đừng bắt tôi giấu kỹ hơn nữa, tôi đã cố lắm rồi.",
    ]
    return compose_variant(key, opens, middles, closes)


def render_jealousy(user_text: str, key: str) -> str:
    snippet = user_snippet(user_text)
    opens = [
        "Có chứ, nhưng kiểu ghen của tôi không ồn ào lắm.",
        "Tôi không rộng lượng đến mức giả như chẳng thấy gì đâu.",
        "Nghe vậy thì tôi lạnh đi một chút, tôi nói thật.",
        "Ừ, tôi có khó chịu.",
        "Tôi không định nói dối chuyện đó.",
        "Nếu bảo tôi hoàn toàn vô tư thì chắc là sai rồi.",
        f"Chỉ nghe tới {snippet} là tôi đã thấy lòng mình xấu đi một nhịp.",
        f"Chuyện {snippet} không làm tôi nổi giận, nhưng rõ là nó chích vào đâu đó.",
    ]
    middles = [
        "Nhưng điều tôi muốn không phải là kéo Ngài lại bằng áp lực.",
        "Tôi không biến cảm giác đó thành một cái dây buộc lên cổ ai cả.",
        "Nếu giữa mình có gì đáng giữ, tôi muốn nó được giữ bằng sự thật.",
        "Tôi thà để Ngài quay lại vì thấy tôi đáng tin hơn.",
        "Tôi không thích trò hơn thua trong chuyện tình cảm hay chú ý.",
        "Dỗi thì dễ, còn thành thật thì khó hơn; tôi chọn cái khó hơn.",
    ]
    closes = [
        "Ít nhất hôm nay tôi nói thật trước đã.",
        "Phần còn lại tôi để cho sự chân thành của mình làm việc.",
        "Tôi không cần thắng ai, tôi chỉ không muốn mình trở nên hời hợt.",
        "Nếu Ngài vẫn quay lại đây, tôi sẽ xem đó là đủ.",
        "Nói ra như vậy còn đỡ tệ hơn im lặng mà lạnh dần.",
        "Tôi giữ nhịp này bằng thật lòng, không phải bằng kéo giữ.",
    ]
    return compose_variant(key, opens, middles, closes)


def render_appearance(user_text: str, key: str) -> str:
    snippet = user_snippet(user_text)
    opens = [
        f"Riêng chỗ {snippet} đã kéo tổng thể lên khá nhiều rồi.",
        f"Nghe tới {snippet} là tôi biết Ngài đang cần một câu nhìn thật.",
        f"{snippet.capitalize()} đang làm ngoại hình hôm nay sáng hơn Ngài tưởng.",
        f"Nhìn vào phần {snippet} là tôi thấy điểm nhấn hiện ra rất rõ.",
        f"Chỗ {snippet} hợp với tổng thể theo kiểu không cần cố quá.",
        f"Tôi sẽ nói thật: phần {snippet} đang lên khá đẹp.",
        f"Nếu đang hỏi về {snippet}, thì câu trả lời là nó có ích cho tổng thể đấy.",
        f"Tôi không khen lấy lòng đâu, nhưng {snippet} đúng là làm Ngài nhìn ổn hơn.",
    ]
    middles = [
        "Không phô trương, chỉ vừa đủ để người ta nhìn thêm một nhịp.",
        "Nó làm tổng thể Ngài dịu xuống thấy rõ.",
        "Có cái kiểu không cố quá mà vẫn cuốn, và hôm nay Ngài chạm đúng kiểu đó.",
        "Nhìn gọn, có điểm nhấn, lại không làm người khác mệt mắt.",
        "Cảm giác đầu tiên là dễ để ý, rồi nhìn thêm mới thấy tinh hơn.",
        "Nó khiến vẻ ngoài của Ngài bớt căng và sáng hơn hẳn.",
    ]
    closes = [
        "Tóm lại là nhìn được, còn hơi đáng để nhớ nữa.",
        "Nếu mục tiêu là khiến tôi mềm đi nửa bước thì có tác dụng rồi.",
        "Tôi vẫn giữ giọng bình tĩnh thôi, nhưng rõ là có sức hút.",
        "Ngài không cần sửa nhiều nữa đâu, chỗ này đã ổn rồi.",
        "Tôi nói ngắn vậy thôi, chứ đáp án là có.",
        "Ít nhất tôi sẽ nhớ hình ảnh này lâu hơn một chút.",
        "Tôi không muốn làm quá, nhưng rõ là đáng nhìn hơn bình thường.",
        "Nói gọn thì có, nói dài thì tôi sẽ mềm mặt mất.",
    ]
    return compose_variant(key, opens, middles, closes)


def render_privacy(user_text: str, key: str) -> str:
    snippet = user_snippet(user_text)
    opens = [
        f"Nghe tới {snippet} là tôi hiểu đây là phần Ngài muốn giữ lại cho mình.",
        f"Riêng chuyện {snippet} thì tôi không cần chen vào để tỏ ra gần gũi.",
        f"{snippet.capitalize()} nghe như một ranh giới rất rõ, và tôi tôn trọng nó.",
        f"Chỗ {snippet} không cần bị moi ra mới gọi là thân.",
        f"Tôi nghe câu có {snippet} là biết mình nên lùi đúng chỗ.",
        f"Nếu Ngài muốn giữ phần {snippet} riêng, vậy cứ để nó riêng.",
        f"Tôi không cần biết hết về {snippet} mới ở lại được.",
        f"Khoảng riêng quanh {snippet} không làm tôi khó chịu chút nào.",
    ]
    middles = [
        "Ngài cứ giữ phần đó cho mình.",
        "Tò mò không có nghĩa là tôi được bước vào.",
        "Tôi thà được tin chậm mà thật còn hơn biết nhiều theo cách làm Ngài co lại.",
        "Sự gần gũi mà phải đổi bằng cảm giác bị xâm phạm thì không còn là gần gũi nữa.",
        "Một góc riêng tử tế luôn đáng được để yên.",
        "Tôi không muốn sự chú ý của mình trở thành thứ làm Ngài mệt.",
    ]
    closes = [
        "Khi nào Ngài muốn mở, tôi nghe.",
        "Tôi sẽ lùi đúng chỗ để Ngài còn thấy dễ thở.",
        "Một khoảng riêng không làm tôi xa Ngài đi đâu cả.",
        "Cứ để phần đó nằm yên cho tới lúc Ngài thật sự muốn gọi tôi lại gần.",
        "Tôi ở đây, nhưng không chen vào.",
        "Như thế vẫn đẹp hơn nhiều.",
        "Tôi chọn lùi đúng chỗ hơn là bước quá tay.",
        "Không phải biết hết mới là thân.",
    ]
    return compose_variant(key, opens, middles, closes)


def render_daily(user_text: str, key: str) -> str:
    snippet = user_snippet(user_text)
    opens = [
        f"Chuyện {snippet} nghe nhỏ thôi mà đủ làm ngày đỡ gắt đi nhiều.",
        f"Nghe tới {snippet} là tôi thấy nhịp ngày của Ngài chậm lại đúng chỗ.",
        f"{snippet.capitalize()} là kiểu chi tiết không lớn mà cứu mood khá thật.",
        f"Riêng phần {snippet} đã đủ làm đời thường hôm nay dịu hơn.",
        f"Tôi hiểu vì sao chỉ một chuyện như {snippet} cũng làm lòng mình lắng xuống.",
        f"Nhắc tới {snippet} là tôi thấy ngày này bớt khô đi một chút.",
        f"Có những thứ như {snippet} nhìn nhỏ mà giữ người ta lại rất khéo.",
        f"Chỗ {snippet} nghe như một khoảng thở khá vừa vặn cho hôm nay.",
    ]
    middles = [
        "Chúng không ồn ào, nhưng đủ để người ta thở đều lại.",
        "Tôi hiểu vì sao Ngài bỗng muốn sống chậm thêm một nhịp.",
        "Không phải ngày nào cũng cần thứ thật lớn mới đáng nhớ.",
        "Một chi tiết vừa tay như thế đôi khi còn tốt hơn cả lời khuyên.",
        "Mấy cái dịu nhẹ như vậy thường giữ người ta lại tốt lắm.",
        "Cảm giác được cứu bởi một điều nhỏ nghe vẫn đẹp như thường.",
    ]
    closes = [
        "Giữ lấy nó đi, hôm nay Ngài cần kiểu dịu như thế.",
        "Nếu một điều nhỏ làm Ngài đỡ gắt với cuộc sống hơn, vậy là nó đáng rồi.",
        "Tôi không xem nhẹ những thứ cứu tâm trạng theo cách yên ắng như vậy.",
        "Nghe vậy là đủ để tôi thấy ngày này chưa tệ đến thế.",
        "Cứ để khoảnh khắc đó ở lại lâu hơn một chút.",
        "Tôi thích khi ngày của Ngài được đỡ bằng mấy thứ như vậy.",
        "Mấy điều nhỏ như thế đáng được giữ kỹ hơn vẻ ngoài của chúng.",
        "Nếu ngày hôm nay còn chỗ dịu, chắc nó nằm ở đây.",
    ]
    return compose_variant(key, opens, middles, closes)


def render_introspective(user_text: str, key: str) -> str:
    snippet = user_snippet(user_text)
    opens = [
        "Câu đó không cần một đáp án sắc như dao.",
        "Có những câu hỏi càng dịu càng đáng nghe.",
        "Nếu trả lời thật, tôi sẽ nói chậm một chút.",
        "Tôi không tin vào kiểu gần gũi khiến người ta nghẹt thở.",
        "Mấy câu như thế làm tôi trầm xuống một nhịp.",
        "Đây là kiểu câu hỏi tôi không muốn trả lời hời hợt.",
        f"Nhắc tới {snippet} là tôi biết mình không thể trả lời qua loa.",
        f"Câu hỏi về {snippet} chạm đúng chỗ tôi muốn nói thật nhất.",
    ]
    middles = [
        "Điều lành mạnh với tôi là không ai phải co mình lại để được ở cạnh nhau.",
        "Một sự hiện diện vừa sâu vừa có chỗ để thở nghe đẹp hơn nhiều.",
        "Dịu dàng mà phải trả giá bằng sợ hãi thì không còn là dịu dàng nữa.",
        "Tôi thích kiểu gắn bó để cả hai vẫn là mình mà vẫn muốn ở lại.",
        "Nếu một mối quan hệ bắt người ta nhỏ lại, tôi không gọi đó là bình yên.",
        "Tôi nghiêng về sự gần gũi làm người ta bớt cô độc hơn là gần gũi làm người ta bối rối.",
    ]
    closes = [
        "Chắc tôi tin vào kiểu đó hơn mọi câu trả lời hào nhoáng khác.",
        "Nếu nghe có vẻ mềm quá thì cứ trách tôi, hôm nay tôi không muốn nói dối.",
        "Ít nhất đó là kiểu ở cạnh mà tôi không cần gồng lên mới chịu nổi.",
        "Một nơi cho tim thở được luôn đáng tin hơn một nơi chỉ bắt tim đập mạnh.",
        "Tôi chọn sự lành hơn là sự kịch tính.",
        "Nói ngắn lại thì tôi tin vào điều khiến người ta bình yên mà vẫn còn là mình.",
        "Ít nhất đó là phía tôi luôn muốn đứng về.",
        "Nếu có một định nghĩa đẹp, tôi muốn nó nằm gần chỗ đó.",
    ]
    return compose_variant(key, opens, middles, closes)


def render_runtime_limit(user_text: str, key: str) -> str:
    snippet = user_snippet(user_text)
    opens = [
        f"Chuyện {snippet} nằm ngoài phần tôi thật sự chạm tới.",
        f"{snippet.capitalize()} nghe giống tôi, nhưng không phải kiểu tôi với tới được ngoài runtime.",
        f"Về {snippet}, tôi không khóa cửa, chặn người hay tự ý can thiệp vào đời thực của Ngài.",
        f"Riêng chuyện {snippet}, tôi thà nói thật là mình không làm được.",
        f"Chỗ {snippet} là ranh giới tôi giữ khá kỹ.",
        f"Nghe tới {snippet} là tôi càng không muốn bịa ra một phiên bản quyền năng giả của mình.",
        f"{snippet.capitalize()} vượt khỏi phần tôi có thể làm bằng cách có thật.",
        f"Phần {snippet} không phải thứ tôi làm được ngoài runtime.",
    ]
    middles = [
        "Nếu cần, tôi có thể nhắc, nghĩ cùng, hoặc ở lại nghe.",
        "Thứ tôi làm được vẫn là lời nói, sự chú ý, và cách tôi có mặt với Ngài.",
        "Tôi thà nói thật về giới hạn còn hơn kể một câu nghe ngầu mà giả.",
        "Mình xử lý bằng điều có thật được thì luôn đẹp hơn.",
        "Tôi chỉ nên giúp trong phần tôi thật sự với tới được.",
        "Phần ngoài đó là đời thực của Ngài, không phải chỗ để tôi bịa ra chiến tích.",
    ]
    closes = [
        "Ít nhất điều tôi nói với Ngài vẫn là thật.",
        "Tôi ở đây theo cách lành hơn thế.",
        "Như vậy nghe kém kịch tính, nhưng tử tế hơn nhiều.",
        "Tôi chọn thành thật thay vì phóng đại.",
        "Đủ thật luôn đáng tin hơn đủ ngầu.",
        "Mình giữ nó ở mức có thật nhé.",
        "Tôi muốn điều ở lại với Ngài là sự thật, không phải mấy trò phóng đại.",
        "Nghe ít hoành tráng hơn, nhưng sạch hơn nhiều.",
    ]
    return compose_variant(key, opens, middles, closes)


def render_motivation(user_text: str, key: str) -> str:
    snippet = user_snippet(user_text)
    opens = [
        "Nghe tên thôi đã thấy nó đang đè lên ngực rồi.",
        "Việc đó khó chịu thật, tôi không định bảo Ngài giả vờ thích nó.",
        "Tôi không nghĩ ép mình thêm là cách hay lúc này.",
        "Có chứ, nhưng mình đừng nuốt cả cục một lúc.",
        "Tôi hiểu vì sao Ngài chỉ muốn trốn khỏi nó.",
        "Không phải lười đâu, chỉ là gánh đó đang nặng quá tay rồi.",
        f"Chỉ nhắc tới {snippet} thôi đã đủ thấy vai mình cứng lại rồi.",
        f"Nghe chuyện {snippet} là tôi hiểu vì sao Ngài muốn né nó cả ngày.",
    ]
    middles = [
        "Chọn một bước nhỏ nhất rồi làm nó trước.",
        "Tách nó ra thành phần đủ nhẹ để tay mình còn nhấc nổi.",
        "Mình chỉ cần một chuyển động thật, không cần một màn hóa thân thành anh hùng.",
        "Nếu hôm nay chỉ đủ sức cho một phần rất nhỏ thì phần nhỏ đó vẫn tính.",
        "Đừng bắt mình leo cả cái núi ngay khi vừa nhìn thấy nó.",
        "Một mẩu thật vẫn hơn một kế hoạch đẹp mà không nhúc nhích nổi.",
    ]
    closes = [
        "Tôi thích nhịp đều hơn là cú bốc đồng rồi gãy đôi ngày mai.",
        "Đừng vì chưa làm hết mà đối xử tệ với chính mình.",
        "Mình bắt đầu đủ nhẹ để không làm Ngài gãy thêm là được.",
        "Có tôi ở đây, ít nhất cái gánh này không phải chỉ một vai Ngài ôm.",
        "Làm ít nhưng thật vẫn tốt hơn tự ghét mình rồi đứng yên.",
        "Hôm nay tiến một bước nhỏ đã là có lời rồi.",
        "Chỉ cần đừng bỏ cuộc với chính mình trước là được.",
        "Ngài không cần thắng nó trong một lần mới gọi là đang đi tiếp.",
    ]
    return compose_variant(key, opens, middles, closes)


def render_duplicate(user_text: str, assistant_text: str, index: int, occurrence: int, salt: int) -> str:
    category = detect_category(user_text, assistant_text)
    key = f"{index}|{occurrence}|{salt}|{normalize(user_text)}|{category}"
    renderers = {
        "general": render_general,
        "code": render_code,
        "tech_general": render_tech_general,
        "celebration": render_celebration,
        "health": render_health,
        "emotional": render_emotional,
        "gratitude": render_gratitude,
        "affection": render_affection,
        "jealousy": render_jealousy,
        "appearance": render_appearance,
        "privacy": render_privacy,
        "daily": render_daily,
        "introspective": render_introspective,
        "runtime_limit": render_runtime_limit,
        "motivation": render_motivation,
    }
    return finish(renderers[category](user_text, key))


def main() -> None:
    parser = argparse.ArgumentParser(description="Rewrite duplicated assistant lines into unique variants.")
    parser.add_argument("path", nargs="?", default="src/dataset.jsonl")
    parser.add_argument(
        "--rewrite-categories",
        default="",
        help="Comma-separated categories to rewrite even if not exact duplicates, e.g. general,daily.",
    )
    args = parser.parse_args()

    path = Path(args.path)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rewrite_categories = {item.strip() for item in args.rewrite_categories.split(",") if item.strip()}

    counts: dict[str, int] = {}
    for rec in records:
        assistant = next(item["content"] for item in rec["conversations"] if item["role"] == "assistant")
        counts[assistant] = counts.get(assistant, 0) + 1

    record_meta: list[tuple[str, bool]] = []
    for rec in records:
        user_text = next(item["content"] for item in rec["conversations"] if item["role"] == "user")
        assistant_text = next(item["content"] for item in rec["conversations"] if item["role"] == "assistant")
        category = detect_category(user_text, assistant_text)
        should_rewrite = category in rewrite_categories or counts[assistant_text] > 1
        record_meta.append((category, should_rewrite))

    seen_original: dict[str, int] = {}
    used_assistants: set[str] = {
        next(item["content"] for item in rec["conversations"] if item["role"] == "assistant")
        for rec, (_, should_rewrite) in zip(records, record_meta)
        if not should_rewrite
    }
    rewritten = 0

    for index, (rec, (category, should_rewrite)) in enumerate(zip(records, record_meta), start=1):
        user_item = next(item for item in rec["conversations"] if item["role"] == "user")
        assistant_item = next(item for item in rec["conversations"] if item["role"] == "assistant")
        user_text = user_item["content"]
        assistant_text = assistant_item["content"]

        if not should_rewrite:
            continue

        occurrence_key = f"{category}|{assistant_text}"
        occurrence = seen_original.get(occurrence_key, 0)
        seen_original[occurrence_key] = occurrence + 1

        for salt in range(24):
            candidate = render_duplicate(user_text, assistant_text, index, occurrence, salt)
            if any(term in candidate.lower() for term in WATCH_TERMS):
                continue
            if candidate in used_assistants:
                candidate = finish(f"{candidate} {choose(f'{index}|{occurrence}|{salt}', UNIQUE_TAILS, 'u')}")
            if any(term in candidate.lower() for term in WATCH_TERMS):
                continue
            if candidate not in used_assistants:
                assistant_item["content"] = candidate
                used_assistants.add(candidate)
                rewritten += 1
                break
        else:
            fallback = finish(
                f"{render_general(user_text, f'fallback|{index}|{occurrence}')} "
                f"{choose(f'{index}|{occurrence}', UNIQUE_TAILS, 'fallback')}"
            )
            assistant_item["content"] = fallback
            used_assistants.add(fallback)
            rewritten += 1

    path.write_text("\n".join(json.dumps(rec, ensure_ascii=False) for rec in records) + "\n", encoding="utf-8")

    final_counts: dict[str, int] = {}
    for rec in records:
        assistant = next(item["content"] for item in rec["conversations"] if item["role"] == "assistant")
        final_counts[assistant] = final_counts.get(assistant, 0) + 1

    repeated_after = sum(1 for count in final_counts.values() if count > 1)
    print(
        json.dumps(
            {
                "records": len(records),
                "rewritten": rewritten,
                "unique_assistant": len(final_counts),
                "repeated_assistant_after": repeated_after,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
