import { useCallback, useRef, useState } from 'react';
import { activityForOp, canStart, type Activity, type ActivityOp } from '../state/activity';

export function useActivity() {
  const [activity, setActivity] = useState<Activity>('idle');
  // Mirror activity for same-tick re-entry before React re-renders (double-click guard).
  const mirror = useRef<Activity>('idle');

  const begin = useCallback((op: ActivityOp): boolean => {
    if (!canStart(mirror.current, op)) return false;
    const next = activityForOp(op);
    mirror.current = next;
    setActivity(next);
    return true;
  }, []);

  const end = useCallback(() => {
    mirror.current = 'idle';
    setActivity('idle');
  }, []);

  return { activity, begin, end };
}
