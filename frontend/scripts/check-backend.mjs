// Read-only connection check. Never registers repositories or starts analysis jobs.
const input=process.argv[2] || process.env.BACKEND_API_URL || "http://127.0.0.1:8000/api/v1";
try {
  const base=new URL(input);
  if(!["http:","https:"].includes(base.protocol)||base.username||base.password||base.search||base.hash)throw new Error("인증 정보·쿼리가 없는 HTTP(S) API 주소를 지정하세요.");
  base.pathname=base.pathname.replace(/\/+$/,"");
  if(!base.pathname.endsWith("/api/v1"))throw new Error("주소 끝에 /api/v1을 포함해 주세요.");
  async function get(path){
    const response=await fetch(path,{headers:{Accept:"application/json"},signal:AbortSignal.timeout(10000)});
    const data=await response.json().catch(()=>null);
    if(!response.ok)throw new Error(`HTTP ${response.status}: ${data?.error?.code || "요청 실패"}`);
    if(!data || typeof data!=="object")throw new Error("JSON 응답을 받지 못했습니다.");
    return data;
  }
  const schemaURL=new URL(base);schemaURL.pathname=schemaURL.pathname.replace(/\/api\/v1$/,"/openapi.json");
  const schema=await get(schemaURL);
  const analysis=Object.entries(schema.paths||{}).find(([p])=>/\/repositories\/\{[^/]+\}\/analyses$/.test(p))?.[1];
  if(!analysis?.post)throw new Error("RepoAtlas 분석 API가 없는 스키마입니다.");
  const listURL=new URL(base.href+"/repositories");listURL.searchParams.set("limit","1");
  const list=await get(listURL);
  if(!Array.isArray(list.items))throw new Error("저장소 목록 응답 형식이 다릅니다.");
  console.log("PASS: OpenAPI와 실제 저장소 목록 API에 접속했습니다.");
  console.log(analysis.post.requestBody ? "분석 요청 본문이 있습니다. 프론트에서 SHA 지원 스키마를 확인합니다." : "현재 서버는 요청 본문 없이 기본 브랜치 HEAD를 분석합니다.");
} catch(error) {
  console.error("FAIL: "+error.message);
  console.error("백엔드의 실행 상태와 제공받은 API 주소를 확인해 주세요.");
  process.exitCode=1;
}
