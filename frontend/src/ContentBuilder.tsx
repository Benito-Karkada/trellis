import { useState } from "react";
import { ChevronDown, ChevronUp, Plus, Trash2 } from "lucide-react";
type Rich = { type: string; text?: string; tag?: string; children?: Rich[] };
type Block = {
  id: string;
  type: string;
  content?: Rich[];
  prompt?: Rich[];
  text?: string;
  language?: string;
  url?: string;
  choices?: { id: string; content: Rich[] }[];
  input?: unknown;
  [key: string]: unknown;
};
type Question = {
  selection?: string;
  correct_choice_ids?: string[];
  answers?: string[];
  [key: string]: unknown;
};
type Grading = { questions?: Record<string, Question>; [key: string]: unknown };
const names: Record<string, string> = {
  document: "Text",
  paragraph: "Text",
  code: "Code example",
  coding: "Coding instructions",
  video: "Video link",
  multiple_choice: "Multiple choice",
  select_all: "Select all",
  fill_blank: "Fill in the blank",
};
const rich = (text: string): Rich[] =>
  text
    .split(/\n\s*\n/)
    .map((p) => ({
      type: "element",
      tag: "p",
      children: [{ type: "text", text: p }],
    }));
function plain(nodes: Rich[]): string | null {
  if (nodes.every((n) => n.type === "text"))
    return nodes.map((n) => n.text || "").join("");
  if (
    nodes.every(
      (n) =>
        n.type === "element" &&
        n.tag === "p" &&
        (n.children || []).every((c) => c.type === "text"),
    )
  )
    return nodes
      .map((n) => n.children!.map((c) => c.text || "").join(""))
      .join("\n\n");
  return null;
}
function TextField({
  label,
  nodes,
  onChange,
  disabled,
}: {
  label: string;
  nodes: Rich[];
  onChange: (nodes: Rich[]) => void;
  disabled: boolean;
}) {
  const text = plain(nodes);
  return (
    <label>
      {label}
      {text === null ? (
        <span className="builder-formatted-note">
          This field includes rich formatting or images. Use Advanced JSON to
          edit it while preserving its layout.
        </span>
      ) : (
        <textarea
          rows={Math.max(3, Math.min(8, text.split("\n").length + 1))}
          value={text}
          disabled={disabled}
          onChange={(e) => onChange(rich(e.target.value))}
        />
      )}
    </label>
  );
}
export default function ContentBuilder({
  content,
  grading,
  onChange,
  disabled,
}: {
  content: string;
  grading: string;
  onChange: (content: string, grading: string) => void;
  disabled: boolean;
}) {
  const [kind, setKind] = useState("document");
  let doc: { version: number; blocks: Block[] }, rules: Grading;
  try {
    doc = JSON.parse(content);
    rules = JSON.parse(grading);
    if (!Array.isArray(doc.blocks) || typeof rules !== "object" || !rules)
      throw Error();
  } catch {
    return (
      <p role="status">
        Finish correcting the JSON before using the content builder.
      </p>
    );
  }
  const save = (blocks: Block[], nextRules = rules) =>
    onChange(
      JSON.stringify({ ...doc, blocks }, null, 2),
      JSON.stringify(nextRules, null, 2),
    );
  const edit = (index: number, changes: Partial<Block>) =>
    save(doc.blocks.map((b, i) => (i === index ? { ...b, ...changes } : b)));
  const question = (id: string, changes: Partial<Question>) =>
    save(doc.blocks, {
      ...rules,
      questions: {
        ...rules.questions,
        [id]: { ...rules.questions?.[id], ...changes },
      },
    });
  function add() {
    const id = "block_" + crypto.randomUUID().slice(0, 8);
    let block: Block = { id, type: kind };
    let next = rules;
    if (kind === "document") block.content = rich("");
    if (kind === "code") Object.assign(block, { text: "", language: "python" });
    if (kind === "video") block.url = "";
    if (
      ["coding", "multiple_choice", "select_all", "fill_blank"].includes(kind)
    )
      block.prompt = rich("");
    if (["multiple_choice", "select_all"].includes(kind)) {
      block.choices = [
        { id: "a", content: rich("") },
        { id: "b", content: rich("") },
      ];
      next = {
        ...rules,
        questions: {
          ...rules.questions,
          [id]: {
            selection: kind === "multiple_choice" ? "one" : "all",
            correct_choice_ids: ["a"],
          },
        },
      };
    }
    if (kind === "fill_blank") {
      block.input = { type: "text" };
      next = {
        ...rules,
        questions: { ...rules.questions, [id]: { answers: [""] } },
      };
    }
    save([...doc.blocks, block], next);
  }
  return (
    <div className="content-builder">
      <p>
        Build the part from text, examples, media, and questions. Save a draft,
        preview it, then publish when it’s ready.
      </p>
      {doc.blocks.map((block, index) => (
        <section className="builder-block" key={block.id}>
          <header>
            <strong>
              {index + 1}. {names[block.type] || block.type}
            </strong>
            <div>
              <button
                aria-label={`Move block ${index + 1} up`}
                disabled={disabled || index === 0}
                onClick={() => {
                  const blocks = [...doc.blocks];
                  [blocks[index - 1], blocks[index]] = [
                    blocks[index],
                    blocks[index - 1],
                  ];
                  save(blocks);
                }}
              >
                <ChevronUp size={16} />
              </button>
              <button
                aria-label={`Move block ${index + 1} down`}
                disabled={disabled || index === doc.blocks.length - 1}
                onClick={() => {
                  const blocks = [...doc.blocks];
                  [blocks[index + 1], blocks[index]] = [
                    blocks[index],
                    blocks[index + 1],
                  ];
                  save(blocks);
                }}
              >
                <ChevronDown size={16} />
              </button>
              <button
                aria-label={`Remove block ${index + 1}`}
                disabled={disabled}
                onClick={() => {
                  const next = { ...rules.questions };
                  delete next[block.id];
                  save(
                    doc.blocks.filter((_, i) => i !== index),
                    { ...rules, questions: next },
                  );
                }}
              >
                <Trash2 size={16} />
              </button>
            </div>
          </header>
          {["document", "paragraph"].includes(block.type) && (
            <TextField
              label="Text"
              nodes={block.content || []}
              disabled={disabled}
              onChange={(content) => edit(index, { content })}
            />
          )}
          {block.prompt && (
            <TextField
              label={block.type === "coding" ? "Instructions" : "Question"}
              nodes={block.prompt}
              disabled={disabled}
              onChange={(prompt) => edit(index, { prompt })}
            />
          )}
          {block.type === "code" && (
            <>
              <label>
                Language
                <input
                  value={block.language || ""}
                  disabled={disabled}
                  onChange={(e) => edit(index, { language: e.target.value })}
                />
              </label>
              <label>
                Example code
                <textarea
                  className="builder-code"
                  rows={7}
                  value={block.text || ""}
                  disabled={disabled}
                  onChange={(e) => edit(index, { text: e.target.value })}
                />
              </label>
            </>
          )}
          {block.type === "video" && (
            <label>
              Video URL
              <input
                type="url"
                value={block.url || ""}
                disabled={disabled}
                onChange={(e) => edit(index, { url: e.target.value })}
              />
            </label>
          )}
          {block.choices && (
            <div className="builder-choices">
              {block.choices.map((choice, c) => (
                <div className="builder-choice" key={choice.id}>
                  <TextField
                    label={`Choice ${c + 1}`}
                    nodes={choice.content}
                    disabled={disabled}
                    onChange={(content) =>
                      edit(index, {
                        choices: block.choices!.map((old, i) =>
                          i === c ? { ...old, content } : old,
                        ),
                      })
                    }
                  />
                  <label className="builder-answer">
                    <input
                      type={
                        block.type === "multiple_choice" ? "radio" : "checkbox"
                      }
                      name={`answer-${block.id}`}
                      checked={(
                        rules.questions?.[block.id]?.correct_choice_ids || []
                      ).includes(choice.id)}
                      disabled={disabled}
                      onChange={(e) =>
                        question(block.id, {
                          selection:
                            block.type === "multiple_choice" ? "one" : "all",
                          correct_choice_ids:
                            block.type === "multiple_choice"
                              ? [choice.id]
                              : e.target.checked
                                ? [
                                    ...new Set([
                                      ...(rules.questions?.[block.id]
                                        ?.correct_choice_ids || []),
                                      choice.id,
                                    ]),
                                  ]
                                : (
                                    rules.questions?.[block.id]
                                      ?.correct_choice_ids || []
                                  ).filter((id) => id !== choice.id),
                        })
                      }
                    />
                    Correct answer
                  </label>
                </div>
              ))}
              <button
                disabled={disabled}
                onClick={() =>
                  edit(index, {
                    choices: [
                      ...block.choices!,
                      {
                        id: crypto.randomUUID().slice(0, 8),
                        content: rich(""),
                      },
                    ],
                  })
                }
              >
                <Plus size={15} />
                Add choice
              </button>
            </div>
          )}
          {block.type === "fill_blank" && (
            <label>
              Accepted answers (one per line)
              <textarea
                rows={3}
                value={(rules.questions?.[block.id]?.answers || []).join("\n")}
                disabled={disabled}
                onChange={(e) =>
                  question(block.id, { answers: e.target.value.split("\n") })
                }
              />
            </label>
          )}
          {!names[block.type] && (
            <p>
              This block is preserved. Use Advanced JSON to change its settings.
            </p>
          )}
        </section>
      ))}
      <div className="builder-add">
        <select
          aria-label="New content block type"
          value={kind}
          disabled={disabled}
          onChange={(e) => setKind(e.target.value)}
        >
          {Object.entries(names)
            .filter(([key]) => key !== "paragraph")
            .map(([key, label]) => (
              <option value={key} key={key}>
                {label}
              </option>
            ))}
        </select>
        <button disabled={disabled} onClick={add}>
          <Plus size={17} />
          Add block
        </button>
      </div>
    </div>
  );
}
