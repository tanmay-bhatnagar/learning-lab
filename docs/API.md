# Initial build API contract
FastAPI localhost:8765; Vite localhost:5173 proxies /api. JSON errors use detail. Files and conversations scoped by validated topic ID. Models have no filesystem tools. Flat JSON persistence lives inside each topic; settings are separate.
GET /api/health
GET /api/topics -> {topics:[{id,name}]}
POST /api/topics {name} -> {id,name}
GET /api/topics/{topic}/files -> {files:[{id,name,status,parser,markdown_name?,error?}]}
POST /api/topics/{topic}/files multipart file and parser (markitdown|anydoc) -> file record (conversion is synchronous in a worker thread)
GET /api/topics/{topic}/files/{file}/markdown -> {markdown:string}
GET /api/topics/{topic}/files/{file}/original -> PDF
GET /api/topics/{topic}/messages -> {messages:[{role,content,thinking?}], context?:object}
POST /api/topics/{topic}/chat {message, file_ids:[], model, think?:bool|string, context_limit:32768} -> NDJSON events {type:thinking|token,text}, {type:done,context:{used,limit,estimated,truncated_messages}}, {type:error,message}. One conversation per topic initially.
GET /api/models -> {models:[{id,name,size_bytes,quantization,parameter_size,thinking:{type:none|toggle|always|levels,levels?:[]}}], error?:string}
GET /api/settings -> {model:string,context_limit:number,parser:string}
PUT /api/settings same object -> settings; browser can persist think per model.

Model module contract (services/api/lab/models.py): async list_models()->dict; async stream_chat(messages:list[dict], model:str, think:bool|str|None, context_limit:int) yields above NDJSON dict events. Context truncation internal; never drop system messages, preserve recent user text; full durable history unaffected. Attachments are separate, trimmable user-context messages and are never treated as trusted system instructions. Modules import package lab. Response-budget cutoffs emit an error and preserve partial output as incomplete.

Context limits: 1,024–32,768, default 32,768. Full topic history is persisted separately from the trimmed request. Files must have a PDF header and fit the 25 MiB upload limit. Localhost-only origin/host checks are enforced. Settings can be isolated with LEARNING_LAB_STATE_ROOT; topics with LEARNING_LAB_ROOT.

Model records also include `display_name` and app-capped `max_context_length`. Completed chat events and saved assistant messages include `model` so the UI can attribute each answer. New settings and omitted upload-parser choices default to anydoc. Unsupported graded thinking requests for toggle-only models are rejected explicitly.
