import React, { useState } from "react";
import { CitationItem, ClarificationOption, TurnItem } from "../services/api";
import { CitationPopover } from "./CitationPopover";
import { ClarificationCard } from "./ClarificationCard";
import { FeedbackBar } from "./FeedbackBar";

interface ChatStreamProps {
  turns: TurnItem[];
  streamingStage?: string | null;
  onSelectClarificationOption: (
    turnId: string,
    option: ClarificationOption
  ) => void;
  onSubmitClarificationText: (text: string) => void;
}

export const ChatStream: React.FC<ChatStreamProps> = ({
  turns,
  streamingStage,
  onSelectClarificationOption,
  onSubmitClarificationText,
}) => {
  const [activeCitation, setActiveCitation] = useState<CitationItem | null>(
    null
  );

  const renderParagraphWithCitations = (
    text: string,
    citations: CitationItem[]
  ) => {
    const citByMarker = new Map(citations.map((c) => [c.marker, c]));
    const parts = text.split(/(\[\d+\])/g);
    return (
      <p className="text-sm text-slate-800 leading-relaxed whitespace-pre-wrap">
        {parts.map((part, idx) => {
          const match = /^\[(\d+)\]$/.exec(part);
          if (match) {
            const num = Number(match[1]);
            const cit = citByMarker.get(num);
            if (cit) {
              return (
                <button
                  key={idx}
                  type="button"
                  onClick={() => setActiveCitation(cit)}
                  className="inline-flex items-center px-1.5 py-0.2 mx-0.5 text-xs font-semibold bg-blue-100 text-blue-800 rounded hover:bg-blue-200"
                  data-testid={`citation-marker-${num}`}
                >
                  [{num}]
                </button>
              );
            }
          }
          return <React.Fragment key={idx}>{part}</React.Fragment>;
        })}
      </p>
    );
  };

  return (
    <div className="space-y-4">
      {turns.map((turn) => (
        <div
          key={turn.id}
          className="bg-white border rounded-xl p-4 shadow-sm space-y-3"
        >
          <div className="text-sm font-semibold text-slate-900 bg-slate-50 p-2.5 rounded-lg">
            Bạn: {turn.question}
          </div>

          {turn.assumptions && turn.assumptions.length > 0 && (
            <div className="text-xs bg-blue-50 text-blue-800 px-3 py-1.5 rounded">
              {turn.assumptions.join(" • ")}
            </div>
          )}

          {turn.limit_reached && (
            <div className="text-xs bg-amber-50 text-amber-800 px-3 py-1.5 rounded">
              Câu trả lời có thể chưa đầy đủ do đã chạm giới hạn bước tra cứu.
            </div>
          )}

          {turn.kind === "clarification" ? (
            <ClarificationCard
              turnId={turn.id}
              question={turn.answer}
              options={turn.clarification_options || []}
              onSelectOption={(opt) => onSelectClarificationOption(turn.id, opt)}
              onSubmitFreeText={onSubmitClarificationText}
            />
          ) : (
            <div className="space-y-3">
              {renderParagraphWithCitations(turn.answer, turn.citations || [])}

              {turn.citations && turn.citations.length > 0 && (
                <div className="bg-slate-50 rounded-lg p-3 space-y-1.5">
                  <div className="text-xs font-semibold text-slate-600">
                    Nguồn trích dẫn:
                  </div>
                  {turn.citations.map((c) => (
                    <div
                      key={c.citation_id}
                      className="text-xs text-slate-700 flex items-center justify-between"
                    >
                      <button
                        type="button"
                        onClick={() => setActiveCitation(c)}
                        className="text-left hover:underline text-blue-700 font-medium"
                      >
                        [{c.marker}] {c.document_title} — {c.section_path}
                        {c.page_start ? ` (Trang ${c.page_start})` : ""} (v
                        {c.version_number})
                      </button>
                    </div>
                  ))}
                </div>
              )}

              <FeedbackBar turnId={turn.id} />
            </div>
          )}
        </div>
      ))}

      {streamingStage && (
        <div className="text-xs text-slate-500 italic px-2">
          Đang xử lý ({streamingStage})...
        </div>
      )}

      {activeCitation && (
        <CitationPopover
          citation={activeCitation}
          onClose={() => setActiveCitation(null)}
        />
      )}
    </div>
  );
};
