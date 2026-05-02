import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, ChevronUp, Loader2, RotateCcw, Send } from 'lucide-react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs) {
  return twMerge(clsx(inputs));
}

function clampTopK(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 5;
  return Math.max(1, Math.min(20, Math.floor(n)));
}

function toNumericOrNull(value) {
  if (value === '' || value === null || value === undefined) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function buildId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function toFriendlyError(message) {
  const text = String(message || 'Unknown error');
  const lower = text.toLowerCase();

  if (lower.includes('not found')) {
    return 'I could not reach the knowledge data right now. Please ensure the backend is running and the IRC corpus is available.';
  }
  if (lower.includes('failed to fetch') || lower.includes('network')) {
    return 'I cannot connect to the backend right now. Please start the API server and try again.';
  }
  if (lower.includes('422')) {
    return 'I had trouble understanding that request. Please try rephrasing your question.';
  }

  return `I ran into an issue: ${text}`;
}

export default function KnowledgeAssistant({ apiBase }) {
  const [draft, setDraft] = useState('');
  const [showPrompts, setShowPrompts] = useState(true);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [topK, setTopK] = useState(5);
  const [pageMin, setPageMin] = useState('');
  const [pageMax, setPageMax] = useState('');
  const [headingContains, setHeadingContains] = useState('');
  const [hasEquation, setHasEquation] = useState(false);
  const composerRef = useRef(null);

  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState([
    {
      id: buildId(),
      role: 'bot',
      text: 'Hi, I am FlexPave Bot. Ask me anything about IRC:37 pavement design, and I will answer in simple language with citations.',
      citations: [],
    },
  ]);

  const inputClass =
    'bg-white border border-gray-300 rounded px-2 py-1 text-xs text-gray-800 outline-none focus:border-orange-500';

  const filterPayload = useMemo(() => {
    const payload = {};
    const min = toNumericOrNull(pageMin);
    const max = toNumericOrNull(pageMax);
    const heading = headingContains.trim();

    if (min !== null) payload.page_min = min;
    if (max !== null) payload.page_max = max;
    if (heading) payload.heading_contains = heading;
    if (hasEquation) payload.has_equation = true;

    return Object.keys(payload).length ? payload : null;
  }, [pageMin, pageMax, headingContains, hasEquation]);

  const quickPrompts = [
    'Show me the fatigue equation and explain variables.',
    'What does IRC:37 say about rutting criteria?',
    'How do I select layer thickness for low CBR subgrade?',
  ];

  useEffect(() => {
    const el = composerRef.current;
    if (!el) return;
    el.style.height = '0px';
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [draft]);

  const postJson = async (url, body) => {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const detail = data?.detail || `HTTP ${res.status}`;
      const err = new Error(detail);
      err.status = res.status;
      throw err;
    }
    return data;
  };

  const askWithFallback = async (userQuery) => {
    const body = {
      query: userQuery,
      top_k: clampTopK(topK),
    };
    if (filterPayload) body.filters = filterPayload;

    let askError = null;
    try {
      const askData = await postJson(`${apiBase}/api/knowledge/ask`, body);
      const answer = String(askData?.answer || '').trim();
      if (answer) {
        return {
          text: answer,
          citations: askData.citations || [],
        };
      }
    } catch (err) {
      askError = err;
    }

    try {
      const searchData = await postJson(`${apiBase}/api/knowledge/search`, body);
      const rows = Array.isArray(searchData?.results) ? searchData.results.slice(0, 3) : [];

      if (rows.length) {
        const summary = rows
          .map((row, index) => {
            const heading = row.heading || 'Relevant section';
            const pageLabel = row.page_start != null && row.page_end != null
              ? `pages ${row.page_start}-${row.page_end}`
              : 'page info unavailable';
            return `${index + 1}. ${heading} (${pageLabel})\n${row.snippet || ''}`;
          })
          .join('\n\n');

        return {
          text: `I could not find one exact direct answer, but these references should help:\n\n${summary}`,
          citations: rows,
        };
      }
    } catch (searchErr) {
      if (askError) {
        throw new Error(askError.message || searchErr.message || 'Unable to answer.');
      }
      throw searchErr;
    }

    if (askError) throw askError;

    return {
      text: 'I could not find a confident answer. Try asking with more context, for example: "fatigue equation with variables" or "rutting criteria in IRC:37".',
      citations: [],
    };
  };

  const addMessage = (role, text, citations = []) => {
    setMessages((prev) => [
      ...prev,
      {
        id: buildId(),
        role,
        text,
        citations,
      },
    ]);
  };

  const resetChat = () => {
    setMessages([
      {
        id: buildId(),
        role: 'bot',
        text: 'Hi, I am FlexPave Bot. Ask me anything about IRC:37 pavement design, and I will answer in simple language with citations.',
        citations: [],
      },
    ]);
  };

  const applyCitationFilters = (citation) => {
    const heading = String(citation?.heading || '').trim();
    const start = toNumericOrNull(citation?.page_start);
    const end = toNumericOrNull(citation?.page_end);

    if (heading) setHeadingContains(heading);
    if (start !== null) setPageMin(String(start));
    if (end !== null) setPageMax(String(end));

    setShowAdvanced(true);
  };

  const sendMessage = async () => {
    const userQuery = draft.trim();
    if (!userQuery || loading) return;

    addMessage('user', userQuery);
    setDraft('');
    setLoading(true);

    try {
      const reply = await askWithFallback(userQuery);
      addMessage('bot', reply.text, reply.citations || []);
    } catch (err) {
      addMessage('bot', toFriendlyError(err.message));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-4 flex flex-col gap-3 h-full min-h-0">
      <div className="flex flex-wrap items-center gap-2 bg-orange-50 border border-orange-200 rounded px-2 py-1.5">
        <div className="text-[10px] text-orange-800 font-bold uppercase tracking-wide">FlexPave Bot: Online</div>
        <div className="text-[10px] text-gray-700">Ask in plain language. Enter sends, Shift+Enter adds a new line.</div>
      </div>

      <div className="border border-orange-100 rounded bg-white px-2 py-1.5">
        <button
          onClick={() => setShowPrompts((v) => !v)}
          className="w-full flex items-center justify-between text-[11px] text-slate-700 hover:text-slate-900"
        >
          <span className="font-medium">Suggested prompts ({quickPrompts.length})</span>
          {showPrompts ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        </button>

        {showPrompts ? (
          <div className="mt-1.5 flex gap-1.5 overflow-x-auto pb-0.5">
            {quickPrompts.map((prompt) => (
              <button
                key={prompt}
                onClick={() => setDraft(prompt)}
                className="shrink-0 text-[10px] px-2 py-1 rounded-full border border-orange-200 bg-white text-orange-800 hover:bg-orange-50"
              >
                {prompt}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      <div className="flex-1 min-h-0 overflow-auto border border-gray-200 rounded bg-white p-3 flex flex-col gap-2">
        {messages.map((msg) => (
          <div key={msg.id} className={cn('flex flex-col gap-1', msg.role === 'user' ? 'items-end' : 'items-start')}>
            <div
              className={cn(
                'max-w-[82%] lg:max-w-[76%] rounded-xl px-3 py-2 text-[13px] leading-6 whitespace-pre-wrap border',
                msg.role === 'user'
                  ? 'bg-orange-500 border-orange-500 text-white'
                  : 'bg-slate-50 border-slate-200 text-slate-800'
              )}
            >
              {msg.text}
            </div>

            {msg.role === 'bot' && Array.isArray(msg.citations) && msg.citations.length > 0 ? (
              <div className="flex flex-wrap gap-1 max-w-[82%] lg:max-w-[76%]">
                {msg.citations.slice(0, 4).map((c, idx) => {
                  const start = c.page_start;
                  const end = c.page_end;
                  const pageLabel = start != null && end != null ? `p.${start}-${end}` : 'p.n/a';
                  const headingLabel = String(c.heading || `Reference ${idx + 1}`).trim();
                  return (
                    <button
                      key={`${c.chunk_id || idx}-${idx}`}
                      type="button"
                      onClick={() => applyCitationFilters(c)}
                      className="text-[10px] text-slate-700 bg-slate-100 border border-slate-200 rounded-full px-2 py-0.5 hover:bg-slate-200 transition-colors max-w-full"
                      title={`${headingLabel} (${pageLabel})`}
                    >
                      <span className="truncate inline-block max-w-[240px] align-bottom">{headingLabel}</span>
                      <span className="mx-1 text-slate-400">•</span>
                      <span className="font-medium">{pageLabel}</span>
                    </button>
                  );
                })}
              </div>
            ) : null}
          </div>
        ))}

        {loading ? (
          <div className="flex items-center gap-2 text-xs text-slate-500 bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 w-fit">
            <Loader2 size={12} className="animate-spin" />
            FlexPave Bot is thinking...
          </div>
        ) : null}
      </div>

      <div className="border border-gray-200 rounded p-2 bg-white flex items-end gap-2">
        <div className="flex-1">
          <label htmlFor="knowledge-query" className="sr-only">Your Question</label>
          <textarea
            id="knowledge-query"
            ref={composerRef}
            rows={1}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
              }
            }}
            className={cn(inputClass, 'w-full resize-none overflow-y-auto min-h-[36px] max-h-[180px] leading-5')}
            placeholder="Ask anything about pavement design, IRC:37, fatigue, rutting, CBR, traffic..."
          />
          <p className="mt-1 text-[10px] text-gray-500">Enter to send · Shift+Enter for new line</p>
        </div>

        <button
          onClick={sendMessage}
          disabled={loading || !draft.trim()}
          className="px-3 py-2 bg-orange-600 hover:bg-orange-700 disabled:bg-gray-300 text-white rounded text-xs font-bold flex items-center gap-1"
        >
          {loading ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
          Ask FlexPave Bot
        </button>
      </div>

      <div className="flex items-center justify-between gap-2">
        <button
          onClick={() => setShowAdvanced((v) => !v)}
          className="text-[11px] text-slate-600 hover:text-slate-900 border border-slate-200 rounded px-2 py-1 bg-white flex items-center gap-1"
        >
          {showAdvanced ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          Advanced options
        </button>

        <button
          onClick={resetChat}
          className="text-[11px] text-slate-600 hover:text-slate-900 border border-slate-200 rounded px-2 py-1 bg-white flex items-center gap-1"
        >
          <RotateCcw size={12} />
          New chat
        </button>
      </div>

      {showAdvanced ? (
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-2 border border-slate-200 rounded p-2 bg-slate-50">
          <div>
            <label className="text-[10px] text-gray-500 font-bold uppercase tracking-wide">Top Results</label>
            <input
              type="number"
              min="1"
              max="20"
              value={topK}
              onChange={(e) => setTopK(e.target.value)}
              className={cn(inputClass, 'w-full mt-1')}
            />
          </div>

          <div>
            <label className="text-[10px] text-gray-500 font-bold uppercase tracking-wide">Page Min</label>
            <input
              type="number"
              min="1"
              value={pageMin}
              onChange={(e) => setPageMin(e.target.value)}
              className={cn(inputClass, 'w-full mt-1')}
              placeholder="e.g. 20"
            />
          </div>

          <div>
            <label className="text-[10px] text-gray-500 font-bold uppercase tracking-wide">Page Max</label>
            <input
              type="number"
              min="1"
              value={pageMax}
              onChange={(e) => setPageMax(e.target.value)}
              className={cn(inputClass, 'w-full mt-1')}
              placeholder="e.g. 60"
            />
          </div>

          <div>
            <label className="text-[10px] text-gray-500 font-bold uppercase tracking-wide">Heading Contains</label>
            <input
              type="text"
              value={headingContains}
              onChange={(e) => setHeadingContains(e.target.value)}
              className={cn(inputClass, 'w-full mt-1')}
              placeholder="e.g. fatigue"
            />
          </div>

          <div className="lg:col-span-4">
            <label className="inline-flex items-center gap-2 text-xs text-gray-700 border border-gray-300 rounded px-2 py-1 bg-white">
              <input
                type="checkbox"
                checked={hasEquation}
                onChange={(e) => setHasEquation(e.target.checked)}
                className="accent-orange-600"
              />
              Prefer equation-containing sections only
            </label>
          </div>
        </div>
      ) : null}
    </div>
  );
}
