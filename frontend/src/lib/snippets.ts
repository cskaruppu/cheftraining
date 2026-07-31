// Code-snippet generator: OpenAI-compatible integration in the
// customer's language and format of choice. All snippets target the
// industry-standard chat completions contract, so existing SDKs work.

export type Lang = "curl" | "python" | "javascript" | "go" | "java";
export type Fmt = "chat" | "json_schema" | "streaming";

export const LANGS: { id: Lang; label: string }[] = [
  { id: "curl", label: "curl" },
  { id: "python", label: "Python" },
  { id: "javascript", label: "JavaScript" },
  { id: "go", label: "Go" },
  { id: "java", label: "Java" },
];

export const FMTS: { id: Fmt; label: string; hint: string }[] = [
  { id: "chat", label: "Chat (JSON)", hint: "standard OpenAI-compatible response" },
  { id: "json_schema", label: "Structured output", hint: "responses validated against your JSON Schema" },
  { id: "streaming", label: "Streaming (SSE)", hint: "token-by-token server-sent events" },
];

const SCHEMA = `{"name":"result","schema":{"type":"object","properties":{"summary":{"type":"string"},"risk_level":{"type":"string","enum":["low","medium","high"]}},"required":["summary","risk_level"]}}`;

export function snippet(lang: Lang, fmt: Fmt, baseUrl: string, model: string, apiKey: string): string {
  const key = apiKey || "<your-api-key>";
  const stream = fmt === "streaming";
  const rf = fmt === "json_schema";

  if (lang === "curl") {
    return `curl -sk ${baseUrl}/v1/chat/completions \\
  -H 'Authorization: Bearer ${key}' \\
  -H 'Content-Type: application/json' \\
  -d '{
    "model": "${model}",${stream ? `\n    "stream": true,` : ""}${rf ? `\n    "response_format": {"type": "json_schema", "json_schema": ${SCHEMA}},` : ""}
    "messages": [{"role": "user", "content": "Summarize the key risks in this contract."}]
  }'`;
  }

  if (lang === "python") {
    return `# pip install openai — any OpenAI-compatible SDK works
from openai import OpenAI

client = OpenAI(base_url="${baseUrl}/v1", api_key="${key}")

${stream ? `stream = client.chat.completions.create(
    model="${model}",
    stream=True,
    messages=[{"role": "user", "content": "Summarize the key risks in this contract."}],
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="", flush=True)` : rf ? `resp = client.chat.completions.create(
    model="${model}",
    response_format={"type": "json_schema", "json_schema": ${SCHEMA}},
    messages=[{"role": "user", "content": "Summarize the key risks in this contract."}],
)
print(resp.choices[0].message.content)  # valid JSON matching your schema` : `resp = client.chat.completions.create(
    model="${model}",
    messages=[{"role": "user", "content": "Summarize the key risks in this contract."}],
)
print(resp.choices[0].message.content)`}`;
  }

  if (lang === "javascript") {
    return `// npm install openai — any OpenAI-compatible SDK works
import OpenAI from "openai";

const client = new OpenAI({ baseURL: "${baseUrl}/v1", apiKey: "${key}" });

${stream ? `const stream = await client.chat.completions.create({
  model: "${model}",
  stream: true,
  messages: [{ role: "user", content: "Summarize the key risks in this contract." }],
});
for await (const chunk of stream) {
  process.stdout.write(chunk.choices[0]?.delta?.content ?? "");
}` : rf ? `const resp = await client.chat.completions.create({
  model: "${model}",
  response_format: { type: "json_schema", json_schema: ${SCHEMA} },
  messages: [{ role: "user", content: "Summarize the key risks in this contract." }],
});
console.log(resp.choices[0].message.content); // valid JSON matching your schema` : `const resp = await client.chat.completions.create({
  model: "${model}",
  messages: [{ role: "user", content: "Summarize the key risks in this contract." }],
});
console.log(resp.choices[0].message.content);`}`;
  }

  if (lang === "go") {
    return `package main

import (
	"bytes"
	"fmt"
	"io"
	"net/http"
)

func main() {
	body := []byte(\`{
	  "model": "${model}",${stream ? `\n	  "stream": true,` : ""}${rf ? `\n	  "response_format": {"type": "json_schema", "json_schema": ${SCHEMA}},` : ""}
	  "messages": [{"role": "user", "content": "Summarize the key risks in this contract."}]
	}\`)
	req, _ := http.NewRequest("POST", "${baseUrl}/v1/chat/completions", bytes.NewBuffer(body))
	req.Header.Set("Authorization", "Bearer ${key}")
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil { panic(err) }
	defer resp.Body.Close()
	out, _ := io.ReadAll(resp.Body)
	fmt.Println(string(out))
}`;
  }

  // java
  return `import java.net.URI;
import java.net.http.*;

public class ModelectClient {
  public static void main(String[] args) throws Exception {
    String body = """
      {
        "model": "${model}",${stream ? `\n        "stream": true,` : ""}${rf ? `\n        "response_format": {"type": "json_schema", "json_schema": ${SCHEMA}},` : ""}
        "messages": [{"role": "user", "content": "Summarize the key risks in this contract."}]
      }""";
    HttpRequest req = HttpRequest.newBuilder()
        .uri(URI.create("${baseUrl}/v1/chat/completions"))
        .header("Authorization", "Bearer ${key}")
        .header("Content-Type", "application/json")
        .POST(HttpRequest.BodyPublishers.ofString(body))
        .build();
    HttpResponse<String> resp = HttpClient.newHttpClient()
        .send(req, HttpResponse.BodyHandlers.ofString());
    System.out.println(resp.body());
  }
}`;
}
