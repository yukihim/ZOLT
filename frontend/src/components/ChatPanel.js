import React, { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

function ChatPanel({ apiBase }) {
  const [messages, setMessages] = useState([
    {
      role: 'system',
      content: '🤖 ZOLT Agent ready. Ask about system health, triage bugs, or find documentation.',
    },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const messagesEndRef = useRef(null);
  const scrollContainerRef = useRef(null);
  const isAtBottomRef = useRef(true);

  // Check if user is at bottom when they scroll
  const handleScroll = () => {
    if (!scrollContainerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollContainerRef.current;
    const atBottom = scrollHeight - scrollTop - clientHeight < 100;
    isAtBottomRef.current = atBottom;
    if (atBottom) setShowScrollButton(false);
  };

  const scrollToBottom = (force = false) => {
    if (force || isAtBottomRef.current) {
        requestAnimationFrame(() => {
            messagesEndRef.current?.scrollIntoView({ behavior: force ? 'smooth' : 'auto' });
        });
    } else {
        setShowScrollButton(true);
    }
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || loading) return;

    const userMsg = { role: 'user', content: text };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      // Build conversation history (exclude system messages)
      const history = messages
        .filter((m) => m.role !== 'system')
        .map((m) => {
          // Flatten blocks back to text for API if needed
          if (m.blocks) {
            return { role: m.role, content: m.blocks.filter(b => b.type === 'text').map(b => b.content).join('\n') };
          }
          return { role: m.role, content: m.content };
        });

      const res = await fetch(`${apiBase}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, conversation_history: history }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      // Add placeholder for streaming assistant message
      setMessages((prev) => [...prev, { role: 'assistant', blocks: [] }]);
      // Keep loading = true until stream finishes

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        let parts = buffer.split('\n\n');
        buffer = parts.pop(); // save incomplete part

        for (let part of parts) {
          const line = part.trim();
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.substring(6));
              
              if (data.type === 'tool_start') {
                setMessages((prev) => {
                  const newMsgs = [...prev];
                  const last = newMsgs[newMsgs.length - 1];
                  if (!last.blocks) last.blocks = [];
                  last.blocks.push({ type: 'tool', name: data.tool, status: 'running', args: data.args });
                  return newMsgs;
                });
              } else if (data.type === 'tool_end') {
                 setMessages((prev) => {
                  const newMsgs = [...prev];
                  const last = newMsgs[newMsgs.length - 1];
                  if (!last.blocks) return newMsgs;
                  
                  // Find the matching running tool block
                  const t = [...last.blocks].reverse().find(b => b.type === 'tool' && b.name === data.tool && b.status === 'running');
                  if (t) {
                    t.status = data.is_error ? 'error' : 'done';
                    t.preview = data.preview;
                  }
                  return newMsgs;
                });
              } else if (data.type === 'token' || data.type === 'message') {
                setMessages((prev) => {
                  const newMsgs = [...prev];
                  const last = newMsgs[newMsgs.length - 1];
                  if (!last.blocks) last.blocks = [];
                  
                  let lastBlock = last.blocks[last.blocks.length - 1];
                  if (!lastBlock || lastBlock.type !== 'text') {
                      lastBlock = { type: 'text', content: '' };
                      last.blocks.push(lastBlock);
                  }
                  lastBlock.content += data.content;
                  return newMsgs;
                });
              } else if (data.type === 'approval_required') {
                setMessages((prev) => {
                  const newMsgs = [...prev];
                  const last = newMsgs[newMsgs.length - 1];
                  if (!last.blocks) last.blocks = [];
                  last.blocks.push({ 
                    type: 'approval', 
                    turnId: data.turn_id, 
                    tool: data.tool, 
                    args: data.args,
                    status: 'pending' 
                  });
                  return newMsgs;
                });
              } else if (data.type === 'error') {
                setMessages((prev) => [
                  ...prev,
                  { role: 'system', content: `⚠️ Error: ${data.error}` }
                ]);
              }
            } catch (err) {
              console.error('SSE parse error', err, line);
            }
          }
        }
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: 'system', content: `⚠️ Error: ${err.message}` },
      ]);
    } finally {
      setLoading(false);
    }
  };
  
  const handleApproval = async (turnId, approved) => {
    try {
      const res = await fetch(`${apiBase}/api/chat/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ turn_id: turnId, approved }),
      });
      if (!res.ok) throw new Error('Failed to send approval');
      
      // Update UI state to show decision
      setMessages((prev) => {
        const newMsgs = [...prev];
        // Find the block across all messages (usually the last one)
        for (let m of newMsgs) {
            if (m.blocks) {
                const block = m.blocks.find(b => b.type === 'approval' && b.turnId === turnId);
                if (block) {
                    block.status = approved ? 'approved' : 'rejected';
                    break;
                }
            }
        }
        return newMsgs;
      });
    } catch (err) {
      console.error('Approval error:', err);
      alert('Could not send approval. Is the backend running?');
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="glass-card" id="chat-panel">
      <div className="card-header-custom">
        <span className="card-header-icon">💬</span>
        <h2>Agent Chat</h2>
      </div>

      {/* Messages */}
      <div 
        className="chat-messages" 
        ref={scrollContainerRef}
        onScroll={handleScroll}
      >
        {messages.map((msg, i) => {
          if (msg.role !== 'assistant' || !msg.blocks) {
             return (
               <div key={i} className={`chat-bubble ${msg.role}`}>
                 <div className="markdown-content">
                    {msg.role === 'user' ? msg.content : <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>}
                 </div>
               </div>
             );
          }

          // Render assistant blocks
          const hasProcessing = msg.blocks.some(b => b.type === 'tool' || b.type === 'approval');
          let processingBlocks = [];
          let finalTextBlock = null;

          if (!hasProcessing) {
             finalTextBlock = { content: msg.blocks.filter(b => b.type === 'text').map(b => b.content).join('') };
          } else {
             const lastBlock = msg.blocks[msg.blocks.length - 1];
             if (lastBlock && lastBlock.type === 'text' && msg.blocks.length > 1) {
                 finalTextBlock = lastBlock;
                 processingBlocks = msg.blocks.slice(0, msg.blocks.length - 1);
             } else {
                 processingBlocks = [...msg.blocks];
             }
          }
          
          let summaryTitle = "Thought process";
          const isLastMessage = i === messages.length - 1;
          const isActive = isLastMessage && loading;
          
          if (isActive) {
             const lastBlock = msg.blocks[msg.blocks.length - 1];
             if (lastBlock?.type === 'tool' && lastBlock.status === 'running') {
                 summaryTitle = `Using ${lastBlock.name}...`;
             } else if (lastBlock?.type === 'approval' && lastBlock.status === 'pending') {
                 summaryTitle = "🛡️ Waiting for your approval...";
             } else {
                 summaryTitle = "Thinking...";
             }
          }

          return (
            <div key={i} className={`chat-bubble ${msg.role}`}>
              {processingBlocks.length > 0 && (
                <details open className="thought-process-details mb-3">
                  <summary className="thought-process-summary">
                    {isActive && <svg className="animate-spin mr-2" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 1 1-6.219-8.56"></path></svg>}
                    <span>{summaryTitle}</span>
                    <span className="thought-chevron">▼</span>
                  </summary>
                  <div className="thought-process-content">
                    {processingBlocks.map((b, idx) => {
                       if (b.type === 'text') {
                          return (
                             <div key={idx} className="thought-text">
                                <ReactMarkdown remarkPlugins={[remarkGfm]}>{b.content}</ReactMarkdown>
                             </div>
                          );
                       } else if (b.type === 'tool') {
                          return (
                             <div key={idx} className="thought-tool">
                                <div className="thought-tool-header">
                                  {b.status === 'running' ? (
                                    <svg className="animate-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 1 1-6.219-8.56"></path></svg>
                                  ) : b.status === 'error' ? '❌' : '⚡'}
                                  <strong>Call <code>{b.name}</code></strong>
                                </div>
                                {b.args && Object.keys(b.args).length > 0 && (
                                  <div className="thought-tool-args">
                                    {JSON.stringify(b.args)}
                                  </div>
                                )}
                                {b.preview && (
                                  <details>
                                    <summary style={{cursor: 'pointer', fontSize: '0.85em', color: b.status === 'error' ? '#ef4444' : '#64748b', marginTop: '6px'}}>
                                      {b.status === 'error' ? 'Error Trace' : 'Result Preview'}
                                    </summary>
                                    <div className="thought-tool-args" style={{maxHeight: '200px', overflowY: 'auto'}}>
                                      {b.preview}
                                    </div>
                                  </details>
                                )}
                             </div>
                          )
                        } else if (b.type === 'approval') {
                           return (
                             <div key={idx} className={`approval-card ${b.status}`}>
                               <div className="approval-header">
                                 <span>🛡️ Permission Required</span>
                               </div>
                               <div className="approval-body">
                                 The agent wants to use <strong>{b.tool}</strong>:
                                 <pre className="approval-args">{JSON.stringify(b.args, null, 2)}</pre>
                               </div>
                               {b.status === 'pending' ? (
                                 <div className="approval-actions">
                                   <button className="btn-approve" onClick={() => handleApproval(b.turnId, true)}>Approve</button>
                                   <button className="btn-reject" onClick={() => handleApproval(b.turnId, false)}>Reject</button>
                                 </div>
                               ) : (
                                 <div className={`approval-result ${b.status}`}>
                                   {b.status === 'approved' ? '✅ Approved' : '❌ Rejected'}
                                 </div>
                               )}
                             </div>
                           );
                        }
                        return null;
                     })}
                  </div>
                </details>
              )}
              
              {finalTextBlock && finalTextBlock.content.trim() && (
                <div className="markdown-content mt-2">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{finalTextBlock.content}</ReactMarkdown>
                </div>
              )}
            </div>
          );
        })}
        
        {loading && (
          <div className="chat-bubble assistant">
            <div className="typing-indicator">
              <span /><span /><span />
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {showScrollButton && (
        <button 
          className="scroll-bottom-btn" 
          onClick={() => {
            isAtBottomRef.current = true;
            scrollToBottom(true);
            setShowScrollButton(false);
          }}
        >
          <span>⬇ New messages below</span>
        </button>
      )}

      {/* Input */}
      <div className="chat-input-area">
        <input
          id="chat-input"
          className="chat-input"
          type="text"
          placeholder="Ask ZOLT something..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={loading}
        />
        <button
          id="btn-send"
          className="btn-send"
          onClick={sendMessage}
          disabled={loading || !input.trim()}
        >
          Send
        </button>
      </div>
    </div>
  );
}

export default ChatPanel;
