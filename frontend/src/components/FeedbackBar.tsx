import React, { useState } from "react";
import { apiRequest } from "../services/api";

interface FeedbackBarProps {
  turnId: string;
}

export const FeedbackBar: React.FC<FeedbackBarProps> = ({ turnId }) => {
  const [rating, setRating] = useState<"helpful" | "not_helpful" | null>(null);
  const [comment, setComment] = useState("");
  const [showComment, setShowComment] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const submitFeedback = async (
    nextRating: "helpful" | "not_helpful",
    note?: string
  ) => {
    setRating(nextRating);
    await apiRequest(`/turns/${turnId}/feedback`, {
      method: "PUT",
      body: JSON.stringify({ rating: nextRating, comment: note || null }),
    });
    setSubmitted(true);
  };

  return (
    <div className="pt-2 border-t border-slate-100 flex flex-col gap-2">
      <div className="flex items-center gap-3 text-xs text-slate-500">
        <span>Đánh giá câu trả lời:</span>
        <button
          type="button"
          onClick={() => void submitFeedback("helpful")}
          className={`px-2 py-0.5 rounded border ${
            rating === "helpful"
              ? "bg-green-100 border-green-300 text-green-800 font-semibold"
              : "hover:bg-slate-100"
          }`}
        >
          Hữu ích
        </button>
        <button
          type="button"
          onClick={() => {
            setRating("not_helpful");
            setShowComment(true);
          }}
          className={`px-2 py-0.5 rounded border ${
            rating === "not_helpful"
              ? "bg-red-100 border-red-300 text-red-800 font-semibold"
              : "hover:bg-slate-100"
          }`}
        >
          Không hữu ích
        </button>
        {submitted && (
          <span className="text-green-700 font-medium">Đã lưu phản hồi</span>
        )}
      </div>

      {showComment && (
        <div className="flex gap-2">
          <input
            type="text"
            placeholder="Ghi chú lý do câu trả lời chưa đúng (tùy chọn)..."
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            className="flex-1 border rounded px-2 py-1 text-xs"
          />
          <button
            type="button"
            onClick={() => {
              void submitFeedback("not_helpful", comment);
              setShowComment(false);
            }}
            className="px-2.5 py-1 bg-slate-800 text-white rounded text-xs"
          >
            Gửi góp ý
          </button>
        </div>
      )}
    </div>
  );
};
