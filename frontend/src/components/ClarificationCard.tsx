import React, { useState } from "react";
import { ClarificationOption } from "../services/api";

interface ClarificationCardProps {
  turnId: string;
  question: string;
  options: ClarificationOption[];
  remainingClarifications?: number;
  onSelectOption: (option: ClarificationOption) => void;
  onSubmitFreeText?: (text: string) => void;
}

export const ClarificationCard: React.FC<ClarificationCardProps> = ({
  question,
  options,
  remainingClarifications = 1,
  onSelectOption,
  onSubmitFreeText,
}) => {
  const [freeText, setFreeText] = useState("");

  return (
    <div
      className="bg-amber-50 border border-amber-200 rounded-xl p-4 space-y-3"
      data-testid="clarification-card"
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-amber-800">
          Cần làm rõ câu hỏi (Còn tối đa {remainingClarifications} lượt hỏi lại)
        </span>
      </div>
      <p className="text-sm font-medium text-slate-900">{question}</p>
      <div className="flex flex-wrap gap-2">
        {options.map((opt) => (
          <button
            key={opt.id}
            type="button"
            onClick={() => onSelectOption(opt)}
            className="px-3 py-1.5 bg-white border border-amber-300 hover:bg-amber-100 rounded-lg text-sm font-medium text-slate-800"
          >
            {opt.label}
          </button>
        ))}
      </div>
      {onSubmitFreeText && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (freeText.trim()) {
              onSubmitFreeText(freeText.trim());
              setFreeText("");
            }
          }}
          className="flex gap-2 pt-1"
        >
          <input
            type="text"
            placeholder="Hoặc nhập câu trả lời làm rõ..."
            value={freeText}
            onChange={(e) => setFreeText(e.target.value)}
            className="flex-1 border rounded px-2.5 py-1 text-sm bg-white"
          />
          <button
            type="submit"
            className="px-3 py-1 bg-amber-700 text-white rounded text-sm"
          >
            Gửi
          </button>
        </form>
      )}
    </div>
  );
};
