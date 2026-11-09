import React, { useState } from "react";
import { apiRequest, DocumentScopeItem } from "../services/api";

interface ScopeSelectorProps {
  selectedDocument: { id: string; title: string } | null;
  onSelectScope: (doc: { id: string; title: string } | null) => void;
}

export const ScopeSelector: React.FC<ScopeSelectorProps> = ({
  selectedDocument,
  onSelectScope,
}) => {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<DocumentScopeItem[]>([]);
  const [open, setOpen] = useState(false);

  const handleSearch = async (q: string) => {
    setQuery(q);
    const items = await apiRequest<DocumentScopeItem[]>(
      `/documents/search?q=${encodeURIComponent(q)}`
    );
    setResults(items);
  };

  if (selectedDocument) {
    return (
      <div
        className="flex items-center gap-2 bg-blue-50 border border-blue-200 text-blue-900 px-3 py-1.5 rounded-lg text-sm"
        data-testid="active-scope-badge"
      >
        <span>
          Phạm vi: <strong>{selectedDocument.title}</strong>
        </span>
        <button
          type="button"
          onClick={() => onSelectScope(null)}
          className="text-xs text-blue-700 underline ml-1"
        >
          Gỡ phạm vi
        </button>
      </div>
    );
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => {
          setOpen(!open);
          if (!open) void handleSearch("");
        }}
        className="px-3 py-1.5 border rounded-lg text-sm text-slate-700 bg-white hover:bg-slate-50"
      >
        Giới hạn 1 tài liệu (tùy chọn)
      </button>
      {open && (
        <div className="absolute left-0 mt-1 w-80 bg-white border rounded-xl shadow-lg p-3 z-40 space-y-2">
          <input
            type="text"
            placeholder="Tìm theo tên tài liệu..."
            value={query}
            onChange={(e) => void handleSearch(e.target.value)}
            className="w-full border rounded px-2.5 py-1.5 text-sm"
          />
          <div className="max-h-48 overflow-y-auto divide-y">
            {results.map((doc) => (
              <button
                key={doc.id}
                type="button"
                onClick={() => {
                  onSelectScope({ id: doc.id, title: doc.title });
                  setOpen(false);
                }}
                className="w-full text-left py-1.5 px-2 hover:bg-slate-50 text-sm"
              >
                <div className="font-medium text-slate-800">{doc.title}</div>
                {doc.effective_from && (
                  <div className="text-xs text-slate-500">
                    Hiệu lực: {doc.effective_from}
                  </div>
                )}
              </button>
            ))}
            {results.length === 0 && (
              <div className="text-xs text-slate-500 py-2 text-center">
                Không có tài liệu phù hợp
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
