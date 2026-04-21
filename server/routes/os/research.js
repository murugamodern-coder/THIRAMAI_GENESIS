const express = require('express');
const router = express.Router();

router.post('/api/os/research/mission', requireAuth, async (req, res) => {
  const { title, question, depth } = req.body;

  // Create mission record
  const missionId = await db.research_missions.create({
    orgId: req.user.orgId,
    title, question, depth,
    status: 'running',
    stage: 1
  });

  // Start async pipeline (non-blocking)
  runResearchPipeline(missionId, question, depth, req.user.orgId)
    .catch(err => console.error('Pipeline error:', err));

  res.json({ ok: true, missionId, status: 'running', stage: 1 });
});

async function runResearchPipeline(missionId, question, depth, orgId) {
  const perplexityKey = await getOSSetting(orgId, 'research', 'perplexity_key');
  const openaiKey = await getOSSetting(orgId, 'research', 'openai_key');

  // Stage 1: Mission decomposition
  await updateMissionStage(missionId, 1, 'Mission decomposition...');
  const subQuestions = await decomposeQuestion(question, openaiKey);

  // Stage 2: Recursive search
  await updateMissionStage(missionId, 2, 'Searching...');
  const perplexity = new PerplexityService(perplexityKey);
  const searchResults = await Promise.all(
    subQuestions.map(q => perplexity.search(q, depth))
  );

  // Stage 3: Synthesis
  await updateMissionStage(missionId, 3, 'Synthesizing findings...');
  const synthesis = await synthesizeResults(searchResults, openaiKey);

  // Stage 4: Reasoning
  await updateMissionStage(missionId, 4, 'Applying reasoning...');
  const reasoned = await applyReasoning(synthesis, question, openaiKey);

  // Stage 5: Report
  await updateMissionStage(missionId, 5, 'Generating report...');
  const report = await generateReport(reasoned, title);

  await db.research_missions.update(missionId, {
    status: 'complete', stage: 5, report
  });
}

// Polling endpoint for mission status
router.get('/api/os/research/mission/:id/status', requireAuth, async (req, res) => {
  const mission = await db.research_missions.find(req.params.id);
  if (!mission) return res.status(404).json({ error: 'Mission not found' });

  res.json({
    stage: mission.stage,
    status: mission.status,
    stageLabel: getStageLabel(mission.stage),
    report: mission.status === 'complete' ? mission.report : null
  });
});

function getStageLabel(stage) {
  switch (stage) {
    case 1: return 'Mission decomposition';
    case 2: return 'Recursive search';
    case 3: return 'Synthesis';
    case 4: return 'Reasoning';
    case 5: return 'Report generation';
    default: return 'Unknown stage';
  }
}

module.exports = router;