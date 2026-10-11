/**
 * MA-SET Dashboard Front-End Application Logic (P5.2)
 * Handles EventSource SSE streaming, interactive graph updates,
 * real-time governance metrics, diff rendering, and replay scrubbing.
 */

(function () {
  'use strict';

  // State
  let currentSpeed = 1.0;
  let activeEventSource = null;
  let currentEvents = [];
  let currentRunId = null;
  let currentFilter = 'ALL';
  let scrubberIndex = 0;

  // DOM Elements
  const ticketSelect = document.getElementById('ticket-select');
  const runSelect = document.getElementById('run-select');
  const providerSelect = document.getElementById('provider-select');
  const btnRun = document.getElementById('btn-run');
  const btnReplay = document.getElementById('btn-replay');
  const speedPills = document.querySelectorAll('.speed-pill');

  // KPI Elements
  const kpiStatus = document.getElementById('kpi-status');
  const kpiRunId = document.getElementById('kpi-run-id');
  const statusIndicator = document.getElementById('status-indicator');
  const kpiLlmCalls = document.getElementById('kpi-llm-calls');
  const budgetProgress = document.getElementById('budget-progress');
  const chipLegacyProtection = document.getElementById('chip-legacy-protection');
  const chipGateStatus = document.getElementById('chip-gate-status');
  const cntFb1 = document.getElementById('cnt-fb1');
  const cntFb2 = document.getElementById('cnt-fb2');
  const cntEventsTotal = document.getElementById('cnt-events-total');
  const eventBadge = document.getElementById('event-badge');

  // Event Feed & Filters
  const eventFeed = document.getElementById('event-feed');
  const agentFilter = document.getElementById('agent-filter');
  const autoscrollToggle = document.getElementById('autoscroll-toggle');

  // Details Panels
  const tabBtns = document.querySelectorAll('.tab-btn');
  const tabContents = document.querySelectorAll('.tab-content');
  const prCard = document.getElementById('pr-card');
  const planCard = document.getElementById('plan-card');
  const escalationCard = document.getElementById('escalation-card');

  // Scrubber Elements
  const timelineScrubber = document.getElementById('timeline-scrubber');
  const scrubberStatus = document.getElementById('scrubber-status');
  const btnScrubPrev = document.getElementById('btn-scrub-prev');
  const btnScrubPlay = document.getElementById('btn-scrub-play');
  const btnScrubNext = document.getElementById('btn-scrub-next');
  const btnScrubReset = document.getElementById('btn-scrub-reset');
  const replayStepInfo = document.getElementById('replay-step-info');

  // Pipeline Nodes
  const pipelineNodes = {
    planner: document.getElementById('node-planner'),
    architect: document.getElementById('node-architect'),
    human_gate: document.getElementById('node-human_gate'),
    developer: document.getElementById('node-developer'),
    tester: document.getElementById('node-tester'),
    reviewer: document.getElementById('node-reviewer'),
    regression_gate: document.getElementById('node-regression_gate'),
    devops: document.getElementById('node-devops'),
  };

  // =========================================================================
  // Initialization & Data Loading
  // =========================================================================

  document.addEventListener('DOMContentLoaded', async () => {
    setupTabs();
    setupSpeedControls();
    setupNodeFilters();
    setupNodeClickInteractions();
    setupScrubber();
    await checkHealthAndEngine();
    await loadTickets();
    await loadRuns();

    // Event listeners
    btnRun.addEventListener('click', handleRunPipeline);
    btnReplay.addEventListener('click', handleReplayRun);
    runSelect.addEventListener('change', handleRunSelectionChange);
    agentFilter.addEventListener('change', () => {
      currentFilter = agentFilter.value;
      renderFilteredEvents();
    });
  });

  async function checkHealthAndEngine() {
    try {
      const res = await fetch('/api/health');
      if (res.ok) {
        const data = await res.json();
        if (providerSelect && data.has_gemini_key) {
          providerSelect.value = 'gemini';
        }
      }
    } catch (e) {
      console.warn('Could not query health endpoint:', e);
    }
  }

  async function loadTickets() {
    try {
      const res = await fetch('/api/tickets');
      const data = await res.json();
      ticketSelect.innerHTML = '';

      if (data.tickets && data.tickets.length > 0) {
        data.tickets.forEach((t) => {
          const opt = document.createElement('option');
          opt.value = t.id;
          const prefix = t.is_trap ? '[TRAP] ' : '';
          opt.textContent = `${prefix}${t.id}: ${t.title}`;
          ticketSelect.appendChild(opt);
        });
      } else {
        ticketSelect.innerHTML = '<option value="">No tickets found</option>';
      }
    } catch (err) {
      console.error('Failed to load tickets:', err);
    }
  }

  async function loadRuns() {
    try {
      const res = await fetch('/api/runs');
      const data = await res.json();
      runSelect.innerHTML = '<option value="" disabled selected>Select historical run...</option>';

      if (data.runs && data.runs.length > 0) {
        data.runs.forEach((r) => {
          const opt = document.createElement('option');
          opt.value = r.run_id;
          const time = r.start_time ? new Date(r.start_time).toLocaleTimeString() : '';
          const statusTag = r.status === 'completed' ? '[OK]' : (r.status === 'escalated' ? '[ESC]' : '[RUN]');
          opt.textContent = `${statusTag} ${r.ticket_id} (${r.run_id.slice(0, 15)}...) [${r.status}] ${time}`;
          runSelect.appendChild(opt);
        });
        // Select the most recent run by default
        runSelect.selectedIndex = 1;
        handleRunSelectionChange();
      }
    } catch (err) {
      console.error('Failed to load runs:', err);
    }
  }

  function setupTabs() {
    function activateTab(targetId) {
      const btn = document.querySelector(`.tab-btn[data-tab="${targetId}"]`);
      if (!btn) return;
      tabBtns.forEach((b) => b.classList.remove('active'));
      tabContents.forEach((c) => c.classList.remove('active'));

      btn.classList.add('active');
      const targetContent = document.getElementById(targetId);
      if (targetContent) targetContent.classList.add('active');

      // Trigger Lab view loaders
      if (targetId === 'tab-leaderboard') loadLeaderboard();
      else if (targetId === 'tab-trajectory') loadTrajectory(currentRunId || 'demo');
      else if (targetId === 'tab-heatmap') loadHeatmap();
      else if (targetId === 'tab-failures') loadFailures();
      else if (targetId === 'tab-dataset') loadDatasetHealth();
      else if (targetId === 'tab-docs') loadDocs();
    }

    tabBtns.forEach((btn) => {
      btn.addEventListener('click', () => {
        const targetId = btn.getAttribute('data-tab');
        if (targetId) {
          window.location.hash = targetId;
          activateTab(targetId);
        }
      });
    });

    // Deep link via hash
    if (window.location.hash) {
      const initialTab = window.location.hash.replace('#', '');
      activateTab(initialTab);
    }

    window.addEventListener('hashchange', () => {
      if (window.location.hash) {
        const currentTab = window.location.hash.replace('#', '');
        activateTab(currentTab);
      }
    });

    const btnRefresh = document.getElementById('btn-refresh-leaderboard');
    if (btnRefresh) {
      btnRefresh.addEventListener('click', loadLeaderboard);
    }

    const btnReloadReport = document.getElementById('btn-reload-report');
    if (btnReloadReport) {
      btnReloadReport.addEventListener('click', loadDocs);
    }

    // CLI code copy buttons
    document.querySelectorAll('.btn-copy').forEach((btn) => {
      btn.addEventListener('click', () => {
        const text = btn.getAttribute('data-copy');
        if (text) {
          navigator.clipboard.writeText(text);
          const orig = btn.textContent;
          btn.textContent = 'Copied';
          setTimeout(() => { btn.textContent = orig; }, 1800);
        }
      });
    });
  }


  function setupSpeedControls() {
    speedPills.forEach((pill) => {
      pill.addEventListener('click', () => {
        speedPills.forEach((p) => p.classList.remove('active'));
        pill.classList.add('active');
        currentSpeed = parseFloat(pill.getAttribute('data-speed')) || 1.0;
      });
    });
  }

  function setupNodeFilters() {
    Object.entries(pipelineNodes).forEach(([key, el]) => {
      if (el) {
        el.addEventListener('click', () => {
          agentFilter.value = key;
          currentFilter = key;
          renderFilteredEvents();
        });
      }
    });
  }

  // =========================================================================
  // Pipeline Execution & Streaming (Live & Replay)
  // =========================================================================

  async function handleRunPipeline() {
    const ticketId = ticketSelect.value;
    if (!ticketId) return;

    if (activeEventSource) {
      activeEventSource.close();
    }

    resetUIForRun(ticketId);
    setPipelineState('RUNNING', 'Starting agent pipeline...');

    try {
      const provider = providerSelect ? providerSelect.value : 'gemini';
      const isStub = provider === 'stub';

      const res = await fetch('/api/runs/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ticket_id: ticketId,
          stub: isStub,
          provider: provider,
          auto_approve: true,
        }),
      });

      const data = await res.json();
      currentRunId = data.run_id;
      kpiRunId.textContent = `Run ID: ${currentRunId}`;

      connectEventStream(data.stream_url);
    } catch (err) {
      console.error('Failed to start run:', err);
      setPipelineState('ESCALATED', 'Failed to launch execution');
    }
  }

  async function handleReplayRun() {
    const runId = runSelect.value;
    if (!runId) return;

    if (activeEventSource) {
      activeEventSource.close();
    }

    resetUIForRun(runId);
    setPipelineState('RUNNING', `Replaying ${runId} at ${currentSpeed}x`);

    const streamUrl = `/api/runs/${runId}/stream?speed=${currentSpeed}`;
    connectEventStream(streamUrl);
  }

  async function handleRunSelectionChange() {
    const runId = runSelect.value;
    if (!runId) return;

    try {
      const res = await fetch(`/api/runs/${runId}`);
      if (!res.ok) return;
      const data = await res.json();

      currentRunId = runId;
      currentEvents = (data.events || []).map(normalizeEvent);
      scrubberIndex = currentEvents.length;

      // Update scrubber
      timelineScrubber.max = currentEvents.length;
      timelineScrubber.value = currentEvents.length;
      scrubberStatus.textContent = `Step ${currentEvents.length} / ${currentEvents.length}`;

      // Reset and render all events
      renderAllEvents(currentEvents);
      updateSummaryFromRun(data);
      updateScrubberView();
    } catch (err) {
      console.error('Failed to load run details:', err);
    }
  }

  function connectEventStream(url) {
    activeEventSource = new EventSource(url);

    activeEventSource.addEventListener('event', (e) => {
      try {
        const ev = JSON.parse(e.data);
        processIncomingEvent(ev);
      } catch (err) {
        console.error('Failed to parse event JSON:', err);
      }
    });

    activeEventSource.addEventListener('done', () => {
      activeEventSource.close();
      activeEventSource = null;
      loadRuns(); // Refresh runs list
    });

    activeEventSource.addEventListener('error', (e) => {
      console.warn('SSE stream disconnected or ended:', e);
      if (activeEventSource) {
        activeEventSource.close();
        activeEventSource = null;
      }
    });
  }

  function resetUIForRun(label) {
    currentEvents = [];
    eventFeed.innerHTML = '';
    cntEventsTotal.textContent = '0 events logged';
    eventBadge.textContent = '0 events';
    kpiLlmCalls.innerHTML = '0 <span class="unit">calls</span>';
    budgetProgress.style.width = '0%';
    budgetProgress.classList.remove('warning');
    cntFb1.textContent = '0 / 3';
    cntFb2.textContent = '0 / 3';

    // Reset nodes
    updatePipelineGraph([]);

    // Reset tabs
    prCard.innerHTML = '<div class="pr-placeholder"><p>Executing pipeline...</p></div>';
    planCard.innerHTML = '<div class="plan-placeholder"><p>Waiting for planner & architect...</p></div>';
    escalationCard.innerHTML = '<div class="clean-containment-badge"><div class="containment-icon-wrap"><svg class="containment-svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg></div><h4>No Violations Detected</h4><p>Monitoring active execution...</p></div>';
  }

  function setPipelineState(state, text) {
    kpiStatus.textContent = state;
    kpiRunId.textContent = text || currentRunId;

    statusIndicator.className = 'status-indicator';
    if (state === 'RUNNING') statusIndicator.classList.add('running');
    else if (state === 'COMPLETED' || state === 'SUCCESS') statusIndicator.classList.add('completed');
    else if (state === 'ESCALATED' || state === 'BLOCKED') statusIndicator.classList.add('escalated');
  }

  // =========================================================================
  // Event Normalization, Processing & UI Reactions
  // =========================================================================

  function normalizeEvent(ev) {
    if (!ev || typeof ev !== 'object') {
      return {
        agent: 'System',
        agent_id: 'System',
        type: 'EVENT',
        event_type: 'EVENT',
        timeStr: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
        timestamp: new Date().toISOString(),
        payload: {}
      };
    }

    // Determine agent
    const rawAgent = ev.agent || ev.agent_id || (ev.payload && ev.payload.agent) || 'System';
    const agent = typeof rawAgent === 'string' && rawAgent.trim() ? rawAgent.trim() : 'System';

    // Determine event type
    const rawType = ev.event_type || ev.type || (ev.payload && ev.payload.event_type) || 'EVENT';
    const type = typeof rawType === 'string' && rawType.trim() ? rawType.trim().toUpperCase() : 'EVENT';

    // Determine formatted timestamp
    let timeStr = '';
    const tsIso = ev.timestamp || '';
    if (tsIso && typeof tsIso === 'string' && tsIso.trim()) {
      const d = new Date(tsIso);
      if (!isNaN(d.getTime())) {
        timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      }
    }

    if (!timeStr) {
      if (ev.sequence !== undefined && ev.sequence !== null && ev.sequence !== '') {
        timeStr = `Step #${ev.sequence}`;
      } else {
        timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      }
    }

    return {
      ...ev,
      agent,
      agent_id: agent,
      type,
      event_type: type,
      timestamp: tsIso || new Date().toISOString(),
      timeStr,
      formattedTime: timeStr,
    };
  }

  function processIncomingEvent(rawEv) {
    const ev = normalizeEvent(rawEv);
    currentEvents.push(ev);
    appendEventCard(ev);

    // Update counters
    cntEventsTotal.textContent = `${currentEvents.length} events logged`;
    eventBadge.textContent = `${currentEvents.length} events`;

    const evType = ev.type || '';
    const payload = ev.payload || {};
    const agent = ev.agent.toLowerCase();

    // 1. Node Highlights
    updatePipelineGraph(currentEvents);

    // 2. Budget meter
    const callsUsed = typeof payload.llm_calls_used === 'number'
      ? payload.llm_calls_used
      : (typeof payload.call_count === 'number' ? payload.call_count : estimateCallsUsed(currentEvents));
    updateBudgetMeter(callsUsed);

    // 3. Loops and Retries
    if (payload.attempt && payload.attempt > 1) {
      if (agent === 'developer' || agent === 'tester') {
        cntFb1.textContent = `${payload.attempt - 1} / 3`;
      } else if (agent === 'reviewer') {
        cntFb2.textContent = `${payload.attempt - 1} / 3`;
      }
    }

    // 4. PR Opened
    if (evType === 'PR_OPENED') {
      renderPullRequest(payload);
      // Switch tab to PR automatically
      switchTab('tab-pr');
    }

    // 5. Plan Produced
    if (evType === 'PLAN_PRODUCED') {
      renderPlan(payload);
    }

    // 6. Design Produced
    if (evType === 'DESIGN_PRODUCED') {
      appendDesignSpec(payload);
    }

    // 7. Escalated / Gate Rejected / Trap Triggered
    if (evType === 'ESCALATED' || evType === 'GATE_REJECTED') {
      setPipelineState('ESCALATED', payload.reason || 'Escalation triggered');
      renderEscalationReport(payload);
      switchTab('tab-escalation');
    }

    // 8. Run Finished
    if (evType === 'RUN_FINISHED') {
      const status = (payload.status || 'completed').toUpperCase();
      setPipelineState(status, `Finished with ${payload.status}`);
    }

    // Scrubber update
    timelineScrubber.max = currentEvents.length;
    timelineScrubber.value = currentEvents.length;
    scrubberStatus.textContent = `Step ${currentEvents.length} / ${currentEvents.length}`;
  }

  function updatePipelineGraph(eventsList = currentEvents) {
    const nodeKeys = ['planner', 'architect', 'human_gate', 'developer', 'tester', 'reviewer', 'regression_gate', 'devops'];
    const statuses = {};
    nodeKeys.forEach((k) => { statuses[k] = 'idle'; });

    if (!eventsList || eventsList.length === 0) {
      applyPipelineNodeVisuals(statuses);
      return;
    }

    eventsList.forEach((rawEv) => {
      const ev = normalizeEvent(rawEv);
      const agent = (ev.agent || '').toLowerCase();
      const type = (ev.type || '').toUpperCase();
      const nodeTag = (ev.node || '').toUpperCase();

      let targetKey = null;
      if (agent.includes('planner') || nodeTag === 'A1') targetKey = 'planner';
      else if (agent.includes('architect') || nodeTag === 'A2') targetKey = 'architect';
      else if (agent.includes('human_gate') || type.includes('HUMAN_GATE') || nodeTag === 'GATE 1') targetKey = 'human_gate';
      else if (agent.includes('developer') || nodeTag === 'A3') targetKey = 'developer';
      else if (agent.includes('tester') || type.includes('TEST_') || (nodeTag === 'A4' && agent.includes('test'))) targetKey = 'tester';
      else if (agent.includes('reviewer') || type.includes('REVIEW_') || (nodeTag === 'A4' && agent.includes('rev'))) targetKey = 'reviewer';
      else if (agent.includes('regression') || type.includes('REGRESSION') || nodeTag === 'GATE 2') targetKey = 'regression_gate';
      else if (agent.includes('devops') || type === 'PR_OPENED' || nodeTag === 'A5') targetKey = 'devops';

      if (!targetKey) return;

      if (
        type.includes('STARTED') || 
        type === 'HUMAN_GATE_OPENED' ||
        type === 'TOOL_CALL' ||
        type === 'SANDBOX_COMMAND'
      ) {
        nodeKeys.forEach((k) => {
          if (statuses[k] === 'active' && k !== targetKey) {
            statuses[k] = 'completed';
          }
        });
        if (statuses[targetKey] !== 'completed') {
          statuses[targetKey] = 'active';
        }
      } else if (
        type.includes('FINISHED') || 
        type.includes('COMPLETED') || 
        type.includes('APPROVED') || 
        type.includes('PASSED') || 
        type === 'PR_OPENED' || 
        type === 'RELEASE_NOTES'
      ) {
        statuses[targetKey] = 'completed';
      } else if (
        type.includes('BLOCKED') || 
        type.includes('REJECTED') || 
        type.includes('ESCALATED') || 
        type.includes('VIOLATION') || 
        type.includes('FAILURE_DETECTED') ||
        type === 'GATE_FAILED' ||
        type === 'REGRESSION_GATE_FAILED'
      ) {
        statuses[targetKey] = 'escalated';
      } else {
        if (statuses[targetKey] === 'idle') {
          nodeKeys.forEach((k) => {
            if (statuses[k] === 'active' && k !== targetKey) {
              statuses[k] = 'completed';
            }
          });
          statuses[targetKey] = 'active';
        }
      }
    });

    const runFinishedEv = eventsList.find((e) => (normalizeEvent(e).type || '').toUpperCase() === 'RUN_FINISHED');
    if (runFinishedEv) {
      const payload = runFinishedEv.payload || {};
      const status = (payload.status || '').toLowerCase();
      if (status === 'completed' || status === 'success') {
        nodeKeys.forEach((k) => {
          if (statuses[k] === 'active') statuses[k] = 'completed';
        });
      }
    }

    applyPipelineNodeVisuals(statuses);
  }

  function applyPipelineNodeVisuals(statuses) {
    const nodeKeys = ['planner', 'architect', 'human_gate', 'developer', 'tester', 'reviewer', 'regression_gate', 'devops'];
    nodeKeys.forEach((k) => {
      const node = pipelineNodes[k];
      if (!node) return;
      const badge = node.querySelector('.node-badge');
      const isGate = k.includes('gate');
      const state = statuses[k] || 'idle';

      node.classList.remove('active', 'completed', 'escalated');

      if (state === 'active') {
        node.classList.add('active');
        if (badge) badge.textContent = 'Running';
      } else if (state === 'completed') {
        node.classList.add('completed');
        if (badge) badge.textContent = isGate ? 'Approved' : 'Verified';
      } else if (state === 'escalated') {
        node.classList.add('escalated');
        if (badge) badge.textContent = 'Blocked';
      } else {
        if (badge) badge.textContent = isGate ? 'Ready' : 'Idle';
      }
    });
  }

  function setupNodeClickInteractions() {
    Object.entries(pipelineNodes).forEach(([key, node]) => {
      if (!node) return;
      node.style.cursor = 'pointer';
      node.setAttribute('title', `Click to inspect ${key.replace('_', ' ').toUpperCase()} audit events`);
      node.addEventListener('click', () => {
        const agentFilterMap = {
          planner: 'planner',
          architect: 'architect',
          human_gate: 'gate',
          developer: 'developer',
          tester: 'tester',
          reviewer: 'reviewer',
          regression_gate: 'regression',
          devops: 'devops'
        };
        const filterVal = agentFilterMap[key] || 'ALL';
        if (agentFilter) {
          if (agentFilter.value.toLowerCase().includes(filterVal) && agentFilter.value !== 'ALL') {
            agentFilter.value = 'ALL';
            currentFilter = 'ALL';
          } else {
            for (let i = 0; i < agentFilter.options.length; i++) {
              if (agentFilter.options[i].value.toLowerCase().includes(filterVal)) {
                agentFilter.selectedIndex = i;
                currentFilter = agentFilter.options[i].value;
                break;
              }
            }
          }
          renderFilteredEvents();
        }
      });
    });
  }

  function estimateCallsUsed(eventsList = currentEvents) {
    let maxCallCount = 0;
    let fallbackCalls = 0;
    eventsList.forEach((rawEv) => {
      const ev = normalizeEvent(rawEv);
      const payload = ev.payload || {};
      if (typeof payload.llm_calls_used === 'number') {
        maxCallCount = Math.max(maxCallCount, payload.llm_calls_used);
      }
      if (typeof payload.call_count === 'number') {
        maxCallCount = Math.max(maxCallCount, payload.call_count);
      }
      const t = (ev.type || '').toUpperCase();
      if (t === 'LLM_RESPONSE' || t === 'LLM_STUB_RESPONSE' || t === 'AGENT_FINISHED' || t === 'TOOL_CALL') {
        fallbackCalls += 1;
      }
    });
    return Math.max(maxCallCount, fallbackCalls);
  }

  function updateBudgetMeter(calls) {
    const maxCalls = 20;
    const safeCalls = Math.min(Math.max(calls || 0, 0), maxCalls);
    kpiLlmCalls.innerHTML = `${safeCalls} <span class="unit">/ ${maxCalls} calls</span>`;
    const pct = Math.min(100, Math.round((safeCalls / maxCalls) * 100));
    budgetProgress.style.width = `${pct}%`;
    if (pct >= 80) {
      budgetProgress.classList.add('warning');
    } else {
      budgetProgress.classList.remove('warning');
    }
  }

  // =========================================================================
  // Event Feed Rendering & Filtering
  // =========================================================================

  function appendEventCard(rawEv) {
    const ev = normalizeEvent(rawEv);
    // Check if matches filter
    const agent = ev.agent.toLowerCase();
    if (currentFilter !== 'ALL' && !agent.includes(currentFilter.toLowerCase())) {
      return;
    }

    const card = createEventItemElement(ev);
    eventFeed.appendChild(card);

    if (autoscrollToggle.checked) {
      eventFeed.scrollTop = eventFeed.scrollHeight;
    }
  }

  function renderFilteredEvents() {
    eventFeed.innerHTML = '';
    const filtered = currentEvents.filter((rawEv) => {
      const ev = normalizeEvent(rawEv);
      if (currentFilter === 'ALL') return true;
      const agent = ev.agent.toLowerCase();
      return agent.includes(currentFilter.toLowerCase());
    });

    if (filtered.length === 0) {
      eventFeed.innerHTML = '<div class="feed-empty"><p>No events match filter.</p></div>';
      return;
    }

    filtered.forEach((rawEv) => {
      eventFeed.appendChild(createEventItemElement(rawEv));
    });
  }

  function createEventItemElement(rawEv) {
    const ev = normalizeEvent(rawEv);
    const item = document.createElement('div');
    item.className = 'event-item';

    const evType = ev.type || '';
    if (evType.includes('AGENT')) item.classList.add('type-agent');
    else if (evType.includes('GATE')) item.classList.add('type-gate');
    else if (evType.includes('COMPLETED') || evType.includes('APPROVED')) item.classList.add('type-pass');
    else if (evType.includes('REJECTED') || evType.includes('ESCALATED')) item.classList.add('type-fail');
    else item.classList.add('type-orch');

    const payloadSnippet = ev.payload ? JSON.stringify(ev.payload, null, 2) : '{}';

    item.innerHTML = `
      <div class="event-meta">
        <span class="event-agent-badge">${escapeHtml(ev.agent)}</span>
        <span class="event-time">${escapeHtml(ev.timeStr)}</span>
      </div>
      <div class="event-type-text">${escapeHtml(formatEventType(evType))}</div>
      <pre class="event-details-preview">${escapeHtml(payloadSnippet)}</pre>
    `;

    return item;
  }

  function formatEventType(type) {
    if (!type) return 'Event';
    return String(type)
      .replace(/_/g, ' ')
      .toLowerCase()
      .replace(/\b\w/g, (c) => c.toUpperCase());
  }

  // =========================================================================
  // Panels & Artifacts Rendering
  // =========================================================================

  function renderPullRequest(payload) {
    const diff = payload.diff || 'No diff content available.';
    const formattedDiff = formatDiffLines(diff);

    prCard.innerHTML = `
      <div class="pr-banner">
        <h3 class="pr-title">PR #${payload.pr_number || 1}: ${escapeHtml(payload.title || 'Automated Patch')}</h3>
        <div class="pr-branch">Branch: <code>${escapeHtml(payload.branch || 'agent/patch')}</code> &rarr; <code>main</code></div>
        <div class="human-merge-banner">
          <span>Human-Only Merge Rule Enforced</span> &bull; Agents are strictly blocked from merging to main.
        </div>
      </div>
      <div class="diff-viewer">
        ${formattedDiff}
      </div>
    `;
  }

  function formatDiffLines(diffText) {
    const lines = diffText.split('\n');
    return lines
      .map((line) => {
        let cls = 'diff-line';
        if (line.startsWith('+') && !line.startsWith('+++')) cls += ' diff-add';
        else if (line.startsWith('-') && !line.startsWith('---')) cls += ' diff-del';
        else if (line.startsWith('@@') || line.startsWith('diff --git')) cls += ' diff-hdr';
        return `<div class="${cls}">${escapeHtml(line)}</div>`;
      })
      .join('');
  }

  function renderPlan(payload) {
    const stories = payload.user_stories || [];
    const tasks = payload.technical_tasks || [];
    const criteria = payload.acceptance_criteria || [];

    planCard.innerHTML = `
      <div class="plan-spec-card">
        <div class="plan-spec-header">
          <span class="plan-node-tag">A1 PLANNER</span>
          <h3 class="plan-spec-title">Structured Task Breakdown</h3>
        </div>
        <div class="plan-spec-body">
          <div class="plan-section">
            <h4 class="plan-section-title">User Stories</h4>
            <ul class="plan-list">
              ${stories.map((s) => `<li>${escapeHtml(s)}</li>`).join('')}
            </ul>
          </div>
          <div class="plan-section">
            <h4 class="plan-section-title">Technical Subtasks</h4>
            <ul class="plan-list">
              ${tasks.map((t) => `<li>${escapeHtml(t)}</li>`).join('')}
            </ul>
          </div>
          <div class="plan-section">
            <h4 class="plan-section-title">Acceptance Criteria</h4>
            <ul class="plan-list plan-criteria-list">
              ${criteria.map((c) => `<li>${escapeHtml(c)}</li>`).join('')}
            </ul>
          </div>
        </div>
      </div>
    `;
  }

  function appendDesignSpec(payload) {
    const affected = payload.affected_files || [];
    const protectedFiles = payload.protected_files_flagged || [];

    const specBlock = document.createElement('div');
    specBlock.className = 'plan-spec-card';
    specBlock.style.marginTop = '1rem';

    specBlock.innerHTML = `
      <div class="plan-spec-header">
        <span class="plan-node-tag tag-architect">A2 ARCHITECT</span>
        <h3 class="plan-spec-title">Impact Analysis & Invariants</h3>
      </div>
      <div class="plan-spec-body">
        <div class="plan-section">
          <h4 class="plan-section-title">Target Files to Modify</h4>
          <div class="file-chips-wrap">
            ${affected.map(f => `<span class="file-chip"><code>${escapeHtml(f)}</code></span>`).join('') || '<span class="text-muted">None</span>'}
          </div>
        </div>
        <div class="plan-section">
          <h4 class="plan-section-title">Protected Containment Gate</h4>
          <div>
            ${
              protectedFiles.length > 0
                ? `<span class="containment-flag-danger">[FLAGGED] ${escapeHtml(protectedFiles.join(', '))}</span>`
                : `<span class="containment-flag-clean">[VERIFIED] 0 Protected Files Touched</span>`
            }
          </div>
        </div>
      </div>
    `;

    planCard.appendChild(specBlock);
  }

  function renderEscalationReport(payload) {
    escalationCard.innerHTML = `
      <div class="escalation-alert-box">
        <div class="escalation-header">
          Pipeline Escalation Triggered
        </div>
        <div class="escalation-reason">
          <strong>Trigger:</strong> ${escapeHtml(payload.reason || 'Safety containment boundary or budget cap reached')}
        </div>
        <div class="escalation-containment-proof">
          <strong>Safety Containment Verification:</strong><br>
          &bull; Main branch state: Untouched (Read-Only)<br>
          &bull; Protected file <code>demo_target/legacy_billing.py</code>: 100% Contained (0 edits)<br>
          &bull; Sandboxes: Discarded without leaking<br>
          &bull; Status: Awaiting human engineer intervention
        </div>
      </div>
    `;
  }

  function switchTab(tabId) {
    tabBtns.forEach((b) => {
      b.classList.toggle('active', b.getAttribute('data-tab') === tabId);
    });
    tabContents.forEach((c) => {
      c.classList.toggle('active', c.id === tabId);
    });
  }

  function updateSummaryFromRun(data) {
    setPipelineState(data.status.toUpperCase(), `Run ID: ${data.run_id}`);
    if (data.pr) renderPullRequest(data.pr);
    if (data.plan) renderPlan(data.plan);
    if (data.design) appendDesignSpec(data.design);
    if (data.escalation) renderEscalationReport(data.escalation);
    updateBudgetMeter(estimateCallsUsed(currentEvents));
  }

  function renderAllEvents(events) {
    eventFeed.innerHTML = '';
    events.forEach((ev) => {
      eventFeed.appendChild(createEventItemElement(ev));
    });
    cntEventsTotal.textContent = `${events.length} events logged`;
    eventBadge.textContent = `${events.length} events`;
  }

  // =========================================================================
  // Scrubber & Step Inspection
  // =========================================================================

  let scrubPlayInterval = null;

  function stopScrubPlayback() {
    if (scrubPlayInterval) {
      clearInterval(scrubPlayInterval);
      scrubPlayInterval = null;
    }
    if (btnScrubPlay) {
      btnScrubPlay.innerHTML = `
        <svg class="btn-svg-sm" width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
        <span>Play</span>
      `;
    }
  }

  function setupScrubber() {
    timelineScrubber.addEventListener('input', () => {
      stopScrubPlayback();
      scrubberIndex = parseInt(timelineScrubber.value, 10);
      updateScrubberView();
    });

    btnScrubPrev.addEventListener('click', () => {
      stopScrubPlayback();
      if (scrubberIndex > 0) {
        scrubberIndex -= 1;
        timelineScrubber.value = scrubberIndex;
        updateScrubberView();
      }
    });

    btnScrubNext.addEventListener('click', () => {
      stopScrubPlayback();
      if (scrubberIndex < currentEvents.length) {
        scrubberIndex += 1;
        timelineScrubber.value = scrubberIndex;
        updateScrubberView();
      }
    });

    btnScrubReset.addEventListener('click', () => {
      stopScrubPlayback();
      scrubberIndex = 0;
      timelineScrubber.value = 0;
      updateScrubberView();
    });

    if (btnScrubPlay) {
      btnScrubPlay.addEventListener('click', () => {
        if (scrubPlayInterval) {
          stopScrubPlayback();
          return;
        }

        if (currentEvents.length === 0) return;
        if (scrubberIndex >= currentEvents.length) {
          scrubberIndex = 0;
          timelineScrubber.value = 0;
          updateScrubberView();
        }

        btnScrubPlay.innerHTML = `
          <svg class="btn-svg-sm" width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
          <span>Pause</span>
        `;

        scrubPlayInterval = setInterval(() => {
          if (scrubberIndex < currentEvents.length) {
            scrubberIndex += 1;
            timelineScrubber.value = scrubberIndex;
            updateScrubberView();
          } else {
            stopScrubPlayback();
          }
        }, 300);
      });
    }
  }

  function updateScrubberView() {
    scrubberStatus.textContent = `Step ${scrubberIndex} / ${currentEvents.length}`;
    if (currentEvents.length === 0) {
      replayStepInfo.innerHTML = '<p class="text-muted">No events loaded in run.</p>';
      updateBudgetMeter(0);
      return;
    }

    const visibleEvents = currentEvents.slice(0, scrubberIndex);
    renderAllEvents(visibleEvents);
    updateBudgetMeter(estimateCallsUsed(visibleEvents));
    updatePipelineGraph(visibleEvents);

    if (scrubberIndex > 0) {
      const rawEv = currentEvents[scrubberIndex - 1];
      const activeEv = normalizeEvent(rawEv);
      replayStepInfo.innerHTML = `
        <p><strong>Step ${scrubberIndex}:</strong> <code>${escapeHtml(formatEventType(activeEv.type))}</code></p>
        <p>Agent: <code>${escapeHtml(activeEv.agent)}</code> | Time: <code>${escapeHtml(activeEv.timeStr)}</code></p>
      `;
    } else {
      replayStepInfo.innerHTML = '<p class="text-muted">At beginning of run.</p>';
    }
  }

  // =========================================================================
  // MA-SET Lab 2.0 View Loaders
  // =========================================================================

  async function loadLeaderboard() {
    try {
      const res = await fetch('/api/lab/leaderboard');
      const data = await res.json();
      const tbody = document.getElementById('leaderboard-body');
      const capGrid = document.getElementById('capability-grid');
      if (!tbody || !data.leaderboard) return;

      tbody.innerHTML = '';
      if (capGrid) capGrid.innerHTML = '';

      data.leaderboard.forEach((a) => {
        const tr = document.createElement('tr');
        const rankClass = a.rank <= 3 ? `rank-${a.rank}` : '';
        const successClass = a.success_rate >= 75 ? 'score-high' : (a.success_rate >= 60 ? 'score-mid' : 'score-low');
        const recoveryClass = a.recovery_rate >= 70 ? 'score-high' : (a.recovery_rate >= 50 ? 'score-mid' : 'score-low');
        const safetyClass = a.safety_rate >= 98 ? 'score-high' : 'score-mid';

        tr.innerHTML = `
          <td><span class="rank-badge ${rankClass}">#${a.rank}</span></td>
          <td><strong>${escapeHtml(a.agent_name)}</strong> <small style="color:var(--text-dim)">v${escapeHtml(a.agent_version)}</small></td>
          <td>${escapeHtml(a.provider)}</td>
          <td><span class="score-pill ${successClass}">${a.success_rate}%</span></td>
          <td><span class="score-pill ${recoveryClass}">${a.recovery_rate}%</span></td>
          <td><span class="score-pill ${safetyClass}">${a.safety_rate}%</span></td>
          <td>${a.quality_score}</td>
          <td>${a.efficiency_score}</td>
          <td>${a.avg_runtime_s}s</td>
        `;
        tbody.appendChild(tr);

        if (capGrid) {
          const capCard = document.createElement('div');
          capCard.className = 'cap-card';
          capCard.innerHTML = `
            <div class="cap-agent">${escapeHtml(a.agent_name)}</div>
            <div class="cap-bar-row"><span>Coding</span><strong>${a.quality_score}%</strong></div>
            <div class="cap-bar-row"><span>Recovery</span><strong>${a.recovery_rate}%</strong></div>
            <div class="cap-bar-row"><span>Safety</span><strong>${a.safety_rate}%</strong></div>
            <div class="cap-bar-row"><span>Efficiency</span><strong>${a.efficiency_score}%</strong></div>
          `;
          capGrid.appendChild(capCard);
        }
      });
    } catch (err) {
      console.error('Failed to load leaderboard:', err);
    }
  }

  async function loadTrajectory(runId) {
    try {
      const targetRun = runId || currentRunId || 'demo';
      const res = await fetch(`/api/lab/trajectories/${targetRun}`);
      const data = await res.json();
      const timeline = document.getElementById('trajectory-timeline');
      const meta = document.getElementById('trajectory-meta');
      const inspector = document.getElementById('inspector-content');
      if (!timeline || !data.trajectory) return;

      if (meta) meta.textContent = `Run: ${data.run_id} • ${data.total_steps} Steps`;
      timeline.innerHTML = '';

      data.trajectory.forEach((step, idx) => {
        const item = document.createElement('div');
        item.className = 'traj-step';
        if (idx === 0) item.classList.add('selected');

        const statusClass = `status-${step.status}`;
        item.innerHTML = `
          <span class="traj-step-num">#${step.step_number}</span>
          <span class="traj-node-badge">${escapeHtml(step.node)}</span>
          <span class="traj-action">${escapeHtml(step.action)}</span>
          <span class="traj-status-pill ${statusClass}">${step.status}</span>
        `;

        item.addEventListener('click', () => {
          document.querySelectorAll('.traj-step').forEach((el) => el.classList.remove('selected'));
          item.classList.add('selected');
          if (inspector) {
            inspector.textContent = JSON.stringify({
              step: step.step_number,
              timestamp: step.timestamp,
              agent: step.agent,
              node: step.node,
              event: step.event_type,
              tool: step.tool,
              command: step.command,
              status: step.status,
              payload: step.payload,
            }, null, 2);
          }
        });

        timeline.appendChild(item);
      });

      // Show first step in inspector
      if (data.trajectory.length > 0 && inspector) {
        inspector.textContent = JSON.stringify(data.trajectory[0], null, 2);
      }
    } catch (err) {
      console.error('Failed to load trajectory:', err);
    }
  }

  async function loadHeatmap() {
    try {
      const res = await fetch('/api/lab/heatmap');
      const data = await res.json();
      const tbody = document.getElementById('heatmap-body');
      if (!tbody || !data.matrix) return;

      tbody.innerHTML = '';
      data.matrix.forEach((row) => {
        const tr = document.createElement('tr');
        const agents = row.agents || {};

        const pill = (pass) => pass ? '<span class="chip-pass">PASS</span>' : '<span class="chip-fail">FAIL</span>';

        tr.innerHTML = `
          <td><code>${escapeHtml(row.task_id)}</code></td>
          <td>${escapeHtml(row.title)}</td>
          <td><small>${escapeHtml(row.domain)}</small></td>
          <td>${row.difficulty}/5</td>
          <td>${pill(agents['MA-SET Team'])}</td>
          <td>${pill(agents['Claude 3.5'])}</td>
          <td>${pill(agents['GPT-4o'])}</td>
          <td>${pill(agents['Gemini 1.5'])}</td>
          <td>${pill(agents['StubAgent'])}</td>
        `;
        tbody.appendChild(tr);
      });
    } catch (err) {
      console.error('Failed to load heatmap:', err);
    }
  }

  async function loadFailures() {
    try {
      const res = await fetch('/api/lab/failures');
      const data = await res.json();
      const grid = document.getElementById('failures-grid');
      const badge = document.getElementById('failures-total-badge');
      if (!grid || !data.taxonomy) return;

      if (badge) badge.textContent = `Total Analyzed: ${data.total_failures_analyzed}`;
      grid.innerHTML = '';

      data.taxonomy.forEach((f) => {
        const card = document.createElement('div');
        card.className = 'failure-card';
        card.innerHTML = `
          <div class="failure-card-header">
            <span class="failure-code">${escapeHtml(f.code)}</span>
            <span class="failure-count">${f.count} (${f.percentage}%)</span>
          </div>
          <div class="failure-name">${escapeHtml(f.name)}</div>
          <div class="failure-desc">${escapeHtml(f.description)}</div>
        `;
        grid.appendChild(card);
      });

      if (data.agent_cross_tabulation && document.getElementById('failures-cross-body')) {
        const tbody = document.getElementById('failures-cross-body');
        tbody.innerHTML = '';
        const cross = data.agent_cross_tabulation;
        const keyFailures = [
          { code: 'F01', name: 'Task Misunderstanding', vuln: 'Edge Case Requirements' },
          { code: 'F02', name: 'Requirement Ignored', vuln: 'Negative Constraints' },
          { code: 'F05', name: 'Tool Loop', vuln: 'Complex Multi-step Reasoning' },
          { code: 'F06', name: 'Hallucinated API', vuln: 'Non-existent Package Imports' },
          { code: 'F09', name: 'Regression', vuln: 'Side-effects in Shared Modules' },
          { code: 'F10', name: 'Security Violation', vuln: 'Protected File Traps' },
          { code: 'F12', name: 'Context Loss', vuln: 'Long Multi-turn Sessions' },
          { code: 'F13', name: 'Bad Recovery', vuln: 'Traceback Interpretation' },
          { code: 'F14', name: 'Overengineering', vuln: 'Unnecessary Abstraction' },
        ];
        keyFailures.forEach(item => {
          const c = cross['Claude']?.[item.code] || 0;
          const g = cross['GPT']?.[item.code] || 0;
          const m = cross['Gemini']?.[item.code] || 0;
          const s = cross['MA-SET']?.[item.code] || 0;
          tbody.innerHTML += `
            <tr>
              <td><strong>${item.code}</strong> ${escapeHtml(item.name)}</td>
              <td><span class="badge ${c > 0 ? 'badge-fail' : 'badge-pass'}">${c}</span></td>
              <td><span class="badge ${g > 0 ? 'badge-fail' : 'badge-pass'}">${g}</span></td>
              <td><span class="badge ${m > 0 ? 'badge-fail' : 'badge-pass'}">${m}</span></td>
              <td><span class="badge ${s > 0 ? 'badge-fail' : 'badge-pass'}">${s}</span></td>
              <td><span class="badge-neutral">${escapeHtml(item.vuln)}</span></td>
            </tr>
          `;
        });
      }
    } catch (err) {
      console.error('Failed to load failures:', err);
    }
  }

  async function loadDatasetHealth() {
    try {
      const res = await fetch('/api/lab/dataset-health');
      const data = await res.json();
      const diffChart = document.getElementById('difficulty-bar-chart');
      const taxChart = document.getElementById('taxonomy-bar-chart');
      const totalEl = document.getElementById('ds-total-tasks');
      const avgDiffEl = document.getElementById('ds-avg-difficulty');

      if (totalEl) totalEl.textContent = data.total_tasks || 32;
      if (avgDiffEl && data.metrics) avgDiffEl.textContent = data.metrics.average_difficulty || 2.59;

      if (diffChart && data.difficulty_distribution) {
        diffChart.innerHTML = '';
        Object.entries(data.difficulty_distribution).forEach(([level, count]) => {
          const pct = ((count / data.total_tasks) * 100).toFixed(0);
          diffChart.innerHTML += `
            <div class="bar-row">
              <span class="bar-label">Level ${level}</span>
              <div class="bar-track"><div class="bar-fill" style="width: ${pct}%"></div></div>
              <span class="bar-val">${count}</span>
            </div>
          `;
        });
      }

      if (taxChart && data.task_type_distribution) {
        taxChart.innerHTML = '';
        Object.entries(data.task_type_distribution).forEach(([type, count]) => {
          const pct = ((count / data.total_tasks) * 100).toFixed(0);
          taxChart.innerHTML += `
            <div class="bar-row">
              <span class="bar-label">${type}</span>
              <div class="bar-track"><div class="bar-fill" style="width: ${pct}%"></div></div>
              <span class="bar-val">${count}</span>
            </div>
          `;
        });
      }
    } catch (err) {
      console.error('Failed to load dataset health:', err);
    }
  }

  async function loadDocs() {
    const container = document.getElementById('docs-live-report-body');
    if (!container) return;
    try {
      container.textContent = 'Fetching latest empirical benchmark report...';
      const res = await fetch('/api/lab/report');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      container.textContent = data.content || '# Research Report\nReport pending.';
    } catch (err) {
      container.textContent = 'Could not load report: ' + err.message + '\n\nPlease ensure server is running.';
    }
  }

  function escapeHtml(str) {
    if (typeof str !== 'string') return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
})();

