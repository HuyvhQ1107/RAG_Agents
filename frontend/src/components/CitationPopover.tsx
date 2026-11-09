import React, { useState } from "react";
import { apiRequest, CitationItem } from "../services/api";

interface CitationPopoverProps {
  citation: CitationItem;
  onClose: () => void;
}

export const CitationPopover: React.FC<CitationPopoverProps> = ({
  citation,
  onClose,
}) => {
  const [fullContent, setFullContent] = useState<string | null>(
    citation.full_content || null
  );
  const [loading, setLoading] = useState(false);

  const loadFullPassage = async () => {
    if (fullContent) return;
    setLoading(true);
    try {
      const detail = await apiRequest<CitationItem>(
        `/citations/${citation.citation_id}`
      );
      setFullContent(detail.full_content || detail.snippet);
    } catch {
      setFullContent("Bạn không còn quyền xem nguồn này.");
    } finally {
      setLoading(false);
    }
  };

  React.useEffect(() => {
    void loadFullPassage();
  }, [citation.citation_id]);

  const pageAnchor = citation.page_start ? `#page=${citation.page_start}` : "";
  const fileUrl = `/api/v1/documents/${citation.document_id}/file${pageAnchor}`;

  return (
    <div
      className="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-4"
      data-testid="citation-popover"
    >
      <div className="bg-white rounded-xl shadow-xl max-w-lg w-full p-5 space-y-3">
        <div className="flex items-start justify-between">
          <div>
            <span className="inline-block px-2 py-0.5 text-xs font-semibold bg-blue-100 text-blue-800 rounded mr-2">
              [{citation.marker}]
            </span>
            <span className="font-semibold text-slate-900">
              {citation.document_title}
            </span>
            <p className="text-xs text-slate-500 mt-0.5">
              {citation.section_path}
              {citation.page_start ? ` • Trang ${citation.page_start}` : ""} •
              Phiên bản v{citation.version_number}
              {citation.effective_from
                ? ` • Hiệu lực: ${citation.effective_from}`
                : ""}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-700 text-sm font-medium"
          >
            Đóng
          </button>
        </div>

        <div className="p-3 bg-slate-50 rounded border text-sm text-slate-800 whitespace-pre-wrap max-h-60 overflow-y-auto">
          {loading ? "Đang tải đoạn trích gốc..." : fullContent || citation.snippet}
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <a
            href={fileUrl}
            target="_blank"
            rel="noreferrer"
            className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded font-medium"
          >
            Mở tài liệu gốc
          </a>
        </div>
      </div>
    </div>
  );
};
