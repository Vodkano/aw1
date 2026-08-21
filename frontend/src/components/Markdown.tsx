import { useMemo } from "react";

/**
 * Render minimo de Markdown para las respuestas del modelo.
 *
 * A proposito NO se interpreta HTML: el texto llega de un modelo que a su vez
 * pudo leer paginas ajenas, asi que todo se pinta como texto plano salvo los
 * bloques de codigo, las negritas y el codigo en linea, que se construyen como
 * nodos de React. Nada de dangerouslySetInnerHTML.
 */

type Block =
  | { kind: "code"; lang: string; body: string }
  | { kind: "text"; body: string };

function split(source: string): Block[] {
  const blocks: Block[] = [];
  const fence = /```([\w+#-]*)\n?([\s\S]*?)(?:```|$)/g;
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = fence.exec(source)) !== null) {
    if (match.index > cursor) {
      blocks.push({ kind: "text", body: source.slice(cursor, match.index) });
    }
    blocks.push({ kind: "code", lang: match[1] ?? "", body: match[2] ?? "" });
    cursor = fence.lastIndex;
  }
  if (cursor < source.length) blocks.push({ kind: "text", body: source.slice(cursor) });
  return blocks;
}

function Inline({ text }: { text: string }) {
  const parts = useMemo(() => text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).filter(Boolean), [text]);
  return (
    <>
      {parts.map((part, index) => {
        if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
          return <code key={index}>{part.slice(1, -1)}</code>;
        }
        if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
          return (
            <strong key={index} className="font-semibold">
              {part.slice(2, -2)}
            </strong>
          );
        }
        return <span key={index}>{part}</span>;
      })}
    </>
  );
}

export function Markdown({ text }: { text: string }) {
  const blocks = useMemo(() => split(text), [text]);

  return (
    <div className="prose-chat">
      {blocks.map((block, index) =>
        block.kind === "code" ? (
          <pre key={index}>
            <code>{block.body.replace(/\n$/, "")}</code>
          </pre>
        ) : (
          block.body
            .split(/\n{2,}/)
            .filter((paragraph) => paragraph.trim())
            .map((paragraph, paragraphIndex) => (
              <p key={`${index}-${paragraphIndex}`} className="whitespace-pre-wrap break-words">
                <Inline text={paragraph.trim()} />
              </p>
            ))
        ),
      )}
    </div>
  );
}
