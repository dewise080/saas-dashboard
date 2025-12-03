import { useState, useCallback, useRef } from 'react';
import type { DragEvent } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  ConnectionMode,
} from '@xyflow/react';
import type {
  ReactFlowInstance,
  OnInit,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { useFlowStore } from './store';
import { Toolbar, ImportModal, ExportModal } from './components/Toolbar';
import { NodeInspector } from './components/NodeInspector';
import { ToolPanel } from './components/ToolPanel';
import { TriggerNode, ActionNode, AINode, DatabaseNode, CommunicationNode, HttpNode } from './components/nodes/CustomNodes';
import type { N8nWorkflow, WorkflowNode, WorkflowEdge } from './types';

// Custom node types mapping
const nodeTypes = {
  trigger: TriggerNode,
  agent: AINode,
  tool: ActionNode,
  default: ActionNode,
  ai: AINode,
  database: DatabaseNode,
  communication: CommunicationNode,
  action: ActionNode,
  http: HttpNode,
};

function App() {
  const [showImportModal, setShowImportModal] = useState(false);
  const [showExportModal, setShowExportModal] = useState(false);
  const [showToolPanel, setShowToolPanel] = useState(true);
  const [exportedWorkflow, setExportedWorkflow] = useState<N8nWorkflow | null>(null);
  
  const reactFlowInstance = useRef<ReactFlowInstance<WorkflowNode, WorkflowEdge> | null>(null);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  
  const {
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,
    setSelectedNode,
    importN8nWorkflow,
    exportToN8n,
    addNode,
  } = useFlowStore();

  // Handle node selection
  const handleNodeClick = useCallback((_: React.MouseEvent, node: any) => {
    setSelectedNode(node.id);
  }, [setSelectedNode]);

  // Handle clicking on the canvas (deselect)
  const handlePaneClick = useCallback(() => {
    setSelectedNode(null);
  }, [setSelectedNode]);

  // Handle import
  const handleImport = useCallback((workflow: N8nWorkflow) => {
    importN8nWorkflow(workflow);
    
    // Fit view after import
    setTimeout(() => {
      reactFlowInstance.current?.fitView({ padding: 0.2 });
    }, 100);
  }, [importN8nWorkflow]);

  // Handle export
  const handleExport = useCallback(() => {
    const workflow = exportToN8n();
    setExportedWorkflow(workflow);
    setShowExportModal(true);
  }, [exportToN8n]);

  // Handle React Flow initialization
  const onInit = useCallback<OnInit<WorkflowNode, WorkflowEdge>>((instance) => {
    reactFlowInstance.current = instance;
  }, []);

  // Handle drag over for adding new nodes
  const onDragOver = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  // Handle drop to add new node
  const onDrop = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();

    const data = event.dataTransfer.getData('application/reactflow');
    if (!data || !reactFlowInstance.current || !reactFlowWrapper.current) return;

    const { type, n8nType, label } = JSON.parse(data);
    
    // Get the position where the node was dropped
    const reactFlowBounds = reactFlowWrapper.current.getBoundingClientRect();
    const position = reactFlowInstance.current.screenToFlowPosition({
      x: event.clientX - reactFlowBounds.left,
      y: event.clientY - reactFlowBounds.top,
    });

    // Create a unique ID
    const newNodeId = `${type}-${Date.now()}`;

    // Create the new node
    const newNode: WorkflowNode = {
      id: newNodeId,
      type: type,
      position,
      data: {
        label: label,
        type: n8nType,
        typeVersion: 1,
        parameters: {},
        credentials: {},
        nodeType: type,
        n8nNode: {
          id: newNodeId,
          name: label,
          type: n8nType,
          typeVersion: 1,
          position: [position.x, position.y],
          parameters: {},
        },
      },
    };

    addNode(newNode);
  }, [addNode]);

  return (
    <div className="h-screen w-screen flex flex-col bg-n8n-dark">
      {/* Top Toolbar */}
      <Toolbar
        onImport={() => setShowImportModal(true)}
        onExport={handleExport}
      />

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Sidebar - Tool Panel */}
        <ToolPanel 
          isOpen={showToolPanel} 
          onToggle={() => setShowToolPanel(!showToolPanel)} 
        />

        {/* Canvas */}
        <div 
          className="flex-1 relative" 
          ref={reactFlowWrapper}
          onDragOver={onDragOver}
          onDrop={onDrop}
        >
          <ReactFlow<WorkflowNode, WorkflowEdge>
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={handleNodeClick}
            onPaneClick={handlePaneClick}
            onInit={onInit}
            nodeTypes={nodeTypes}
            connectionMode={ConnectionMode.Loose}
            fitView
            defaultEdgeOptions={{
              type: 'smoothstep',
              style: { stroke: '#555', strokeWidth: 2 },
              animated: false,
            }}
            proOptions={{ hideAttribution: true }}
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={20}
              size={1}
              color="#333"
            />
            <Controls className="!bg-n8n-gray !border-gray-600" />
            <MiniMap
              className="!bg-n8n-gray"
              nodeColor={(node) => {
                switch (node.data?.nodeType) {
                  case 'trigger':
                    return '#22c55e';
                  case 'agent':
                    return '#a855f7';
                  case 'tool':
                    return '#3b82f6';
                  default:
                    return '#6b7280';
                }
              }}
              maskColor="rgba(0, 0, 0, 0.6)"
            />
          </ReactFlow>

          {/* Empty state */}
          {nodes.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <div className="text-center text-gray-500">
                <div className="text-6xl mb-4">🔧</div>
                <h2 className="text-xl font-semibold mb-2">No workflow loaded</h2>
                <p className="text-sm mb-2">
                  Click <span className="text-blue-400">Import JSON</span> to load an n8n workflow
                </p>
                <p className="text-sm">
                  Or drag nodes from the <span className="text-green-400">Tool Panel</span> on the left
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Right Sidebar - Node Inspector */}
        <NodeInspector />
      </div>

      {/* Modals */}
      <ImportModal
        isOpen={showImportModal}
        onClose={() => setShowImportModal(false)}
        onImport={handleImport}
      />
      <ExportModal
        isOpen={showExportModal}
        onClose={() => setShowExportModal(false)}
        workflow={exportedWorkflow}
      />
    </div>
  );
}

export default App;
