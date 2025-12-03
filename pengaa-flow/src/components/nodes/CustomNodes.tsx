import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { NodeProps } from '@xyflow/react';
import type { WorkflowNodeData } from '../../types';

interface BaseNodeProps {
  data: WorkflowNodeData;
  selected: boolean;
  colorClass: string;
  icon: string;
}

const BaseNode = memo(({ data, selected, colorClass, icon }: BaseNodeProps) => {
  return (
    <div className={`custom-node ${colorClass} ${selected ? 'selected' : ''}`}>
      {/* Shine overlay for glass effect */}
      <div className="node-shine" />
      
      {/* Content */}
      <div className="node-row">
        <div className="node-icon">
          {icon}
        </div>
        <div>
          <div className="node-title">{data.label}</div>
          <div className="node-subtitle">
            {data.type.split('.').pop()?.replace(/([A-Z])/g, ' $1').trim()}
          </div>
        </div>
      </div>
      
      {/* Parameters/Credentials badges */}
      {(Object.keys(data.parameters).length > 0 || (data.credentials && Object.keys(data.credentials).length > 0)) && (
        <div className="mt-2 flex gap-1 flex-wrap">
          {Object.keys(data.parameters).length > 0 && (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-white/10 text-white/70">
              ⚙️ {Object.keys(data.parameters).length}
            </span>
          )}
          {data.credentials && Object.keys(data.credentials).length > 0 && (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-white/10 text-white/70">
              🔑 {Object.keys(data.credentials).length}
            </span>
          )}
        </div>
      )}

      {/* Handles */}
      <Handle
        type="target"
        position={Position.Left}
      />
      <Handle
        type="source"
        position={Position.Right}
      />
    </div>
  );
});

BaseNode.displayName = 'BaseNode';

// Trigger Node (emerald green)
export const TriggerNode = memo((props: NodeProps) => (
  <BaseNode
    data={props.data as WorkflowNodeData}
    selected={props.selected || false}
    colorClass="emerald"
    icon="⚡"
  />
));
TriggerNode.displayName = 'TriggerNode';

// Action Node (blue)
export const ActionNode = memo((props: NodeProps) => (
  <BaseNode
    data={props.data as WorkflowNodeData}
    selected={props.selected || false}
    colorClass="blue"
    icon="▶️"
  />
));
ActionNode.displayName = 'ActionNode';

// AI Node (purple)
export const AINode = memo((props: NodeProps) => (
  <BaseNode
    data={props.data as WorkflowNodeData}
    selected={props.selected || false}
    colorClass="purple"
    icon="🤖"
  />
));
AINode.displayName = 'AINode';

// Database Node (orange)
export const DatabaseNode = memo((props: NodeProps) => (
  <BaseNode
    data={props.data as WorkflowNodeData}
    selected={props.selected || false}
    colorClass="orange"
    icon="🗄️"
  />
));
DatabaseNode.displayName = 'DatabaseNode';

// Communication Node (pink)
export const CommunicationNode = memo((props: NodeProps) => (
  <BaseNode
    data={props.data as WorkflowNodeData}
    selected={props.selected || false}
    colorClass="pink"
    icon="💬"
  />
));
CommunicationNode.displayName = 'CommunicationNode';

// HTTP/API Node (cyan)
export const HttpNode = memo((props: NodeProps) => (
  <BaseNode
    data={props.data as WorkflowNodeData}
    selected={props.selected || false}
    colorClass="cyan"
    icon="🔗"
  />
));
HttpNode.displayName = 'HttpNode';

export const nodeTypes = {
  trigger: TriggerNode,
  action: ActionNode,
  ai: AINode,
  database: DatabaseNode,
  communication: CommunicationNode,
  http: HttpNode,
};
