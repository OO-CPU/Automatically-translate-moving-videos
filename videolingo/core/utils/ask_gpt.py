import os
import json
from threading import Lock
import json_repair
from openai import OpenAI
from core.utils.config_utils import load_key
from rich import print as rprint
from core.utils.decorator import except_handler

# ------------
# cache gpt response
# ------------

LOCK = Lock()
GPT_LOG_FOLDER = 'output/gpt_log'


def _normalize_json_response(resp):
    """兼容部分 OpenAI 兼容模型把单个 JSON 对象包在数组中的情况。"""
    if isinstance(resp, list) and len(resp) == 1 and isinstance(resp[0], dict):
        return resp[0]
    return resp

def _save_cache(model, prompt, resp_content, resp_type, resp, message=None, log_title="default"):
    with LOCK:
        logs = []
        file = os.path.join(GPT_LOG_FOLDER, f"{log_title}.json")
        os.makedirs(os.path.dirname(file), exist_ok=True)
        if os.path.exists(file):
            with open(file, 'r', encoding='utf-8') as f:
                logs = json.load(f)
        logs.append({"model": model, "prompt": prompt, "resp_content": resp_content, "resp_type": resp_type, "resp": resp, "message": message})
        with open(file, 'w', encoding='utf-8') as f:
            json.dump(logs, f, ensure_ascii=False, indent=4)

def _load_cache(prompt, resp_type, log_title):
    with LOCK:
        file = os.path.join(GPT_LOG_FOLDER, f"{log_title}.json")
        if os.path.exists(file):
            with open(file, 'r', encoding='utf-8') as f:
                for item in json.load(f):
                    if item["prompt"] == prompt and item["resp_type"] == resp_type:
                        return item["resp"]
        return False

# ------------
# ask gpt once
# ------------

@except_handler("GPT request failed", retry=5)
def ask_gpt(prompt, resp_type=None, valid_def=None, log_title="default"):
    if not load_key("api.key"):
        raise ValueError("API key is not set")
    # check cache
    cached = _load_cache(prompt, resp_type, log_title)
    if cached:
        rprint("use cache response")
        return cached

    model = load_key("api.model")
    base_url = load_key("api.base_url")
    if 'ark' in base_url:
        base_url = "https://ark.cn-beijing.volces.com/api/v3" # huoshan base url
    elif 'v1' not in base_url:
        base_url = base_url.strip('/') + '/v1'
    client = OpenAI(api_key=load_key("api.key"), base_url=base_url)
    response_format = {"type": "json_object"} if resp_type == "json" and load_key("api.llm_support_json") else None

    messages = [{"role": "user", "content": prompt}]

    params = dict(
        model=model,
        messages=messages,
        response_format=response_format,
        timeout=300
    )
    # 字幕翻译不需要思维链。千问关闭思考后结构化输出更稳定，也减少输出 token。
    if str(model).lower().startswith("qwen"):
        params["extra_body"] = {"enable_thinking": False}

    # 若首次结构不合规，把具体错误反馈给模型纠正一次。
    for correction_attempt in range(2):
        resp_raw = client.chat.completions.create(**params)
        resp_content = resp_raw.choices[0].message.content or ""
        if resp_type == "json":
            resp = _normalize_json_response(json_repair.loads(resp_content))
        else:
            resp = resp_content

        if valid_def:
            try:
                valid_resp = valid_def(resp)
            except Exception as exc:
                valid_resp = {"status": "error", "message": f"Validator error: {exc}"}
            if valid_resp['status'] != 'success':
                message = valid_resp['message']
                _save_cache(model, prompt, resp_content, resp_type, resp, log_title="error", message=message)
                if correction_attempt == 0:
                    messages.extend([
                        {"role": "assistant", "content": resp_content},
                        {
                            "role": "user",
                            "content": (
                                f"Your previous response failed validation: {message}. "
                                "Return the complete corrected result as one non-empty JSON object. "
                                "Do not return a JSON array and do not omit any requested numbered keys."
                            ),
                        },
                    ])
                    continue
                raise ValueError(f"❎ API response error: {message}")

        _save_cache(model, prompt, resp_content, resp_type, resp, log_title=log_title)
        return resp


if __name__ == '__main__':
    from rich import print as rprint
    
    result = ask_gpt("""test respond ```json\n{\"code\": 200, \"message\": \"success\"}\n```""", resp_type="json")
    rprint(f"Test json output result: {result}")
