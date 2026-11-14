"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Badge, Button, Panel, Segmented } from "@/components/ui";
import { copy } from "@/lib/copy";
import { dateTime } from "@/lib/format";
import type { DocumentRow } from "@/lib/rows";

type Kind = "owner_letter" | "emergency_card" | "registry_list";
const KINDS: { value: Kind; label: string }[] = [
  { value: "owner_letter", label: "Owner letter" },
  { value: "emergency_card", label: "Emergency card" },
  { value: "registry_list", label: "Registry list" },
];

function printCard() {
  document.body.dataset.print = "card";
  const done = () => {
    delete document.body.dataset.print;
    window.removeEventListener("afterprint", done);
  };
  window.addEventListener("afterprint", done);
  window.print();
}

/** The Fixer's three documents (spec section 9.6), newest of each kind. */
export function DocumentsTab({ documents, loaded }: { documents: DocumentRow[]; loaded: boolean }) {
  const [kind, setKind] = useState<Kind>("emergency_card");
  const latest = (k: Kind) =>
    documents
      .filter((d) => d.kind === k)
      .sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""))[0];
  const doc = latest(kind);

  return (
    <Panel
      title="Documents"
      right={
        <Segmented
          size="sm"
          value={kind}
          onChange={setKind}
          options={KINDS.map((k) => ({ value: k.value, label: k.label, disabled: !latest(k.value) && loaded && documents.length > 0 }))}
        />
      }
    >
      {!doc ? (
        <p className="text-sm text-muted">
          {loaded ? "The Fixer has not written this document for the building yet." : "Loading"}
        </p>
      ) : (
        <div>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            {kind === "owner_letter" && <Badge tone="decision">{copy.ownerLetterDraft}</Badge>}
            <span className="text-xs text-muted">written {dateTime(doc.created_at)}</span>
            {kind === "emergency_card" && (
              <Button size="sm" className="ml-auto" onClick={printCard}>
                Print card
              </Button>
            )}
          </div>
          <article
            id={kind === "emergency_card" ? "print-card" : undefined}
            className="doc max-h-[520px] overflow-y-auto rounded-md border border-line bg-panel-2 p-5 text-[0.95rem]"
          >
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{doc.content_md ?? ""}</ReactMarkdown>
          </article>
        </div>
      )}
    </Panel>
  );
}
