package main

import (
	"testing"
	"time"
)

func TestEffectiveRefresh(t *testing.T) {
	tests := []struct {
		name       string
		minRefresh int
		refresh    int
		want       time.Duration
	}{
		{"unset floor uses default", 0, 10, defaultMinRefresh * time.Second},
		{"zero refresh clamped", 0, 0, defaultMinRefresh * time.Second},
		{"above default kept", 0, 300, 300 * time.Second},
		{"configured floor", 120, 10, 120 * time.Second},
		{"configured floor below request", 30, 45, 45 * time.Second},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := effectiveRefresh(tt.refresh, tt.minRefresh); got != tt.want {
				t.Errorf("effectiveRefresh(%d) with min %d = %s, want %s", tt.refresh, tt.minRefresh, got, tt.want)
			}
		})
	}
}

func TestJitterWithinTenPercent(t *testing.T) {
	d := 300 * time.Second
	for i := 0; i < 1000; i++ {
		got := jitter(d)
		if got < d*9/10 || got > d*11/10 {
			t.Fatalf("jitter(%s) = %s, outside ±10%%", d, got)
		}
	}
}

func TestSameAttributes(t *testing.T) {
	tests := []struct {
		name string
		a, b map[string]interface{}
		want bool
	}{
		{
			"reordered multi-value",
			map[string]interface{}{"uncEmail": []string{"a@x", "b@x"}, "uid": "u"},
			map[string]interface{}{"uncEmail": []string{"b@x", "a@x"}, "uid": "u"},
			true,
		},
		{
			"different multi-value",
			map[string]interface{}{"uncEmail": []string{"a@x", "b@x"}},
			map[string]interface{}{"uncEmail": []string{"a@x", "c@x"}},
			false,
		},
		{
			"duplicate counts differ",
			map[string]interface{}{"v": []string{"a", "a", "b"}},
			map[string]interface{}{"v": []string{"a", "b", "b"}},
			false,
		},
		{
			"value removed",
			map[string]interface{}{"v": []string{"a", "b"}},
			map[string]interface{}{"v": "a"},
			false,
		},
		{
			"attribute added",
			map[string]interface{}{"uid": "u"},
			map[string]interface{}{"uid": "u", "cn": "c"},
			false,
		},
		{
			"single value changed",
			map[string]interface{}{"uid": "u"},
			map[string]interface{}{"uid": "v"},
			false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := sameAttributes(tt.a, tt.b); got != tt.want {
				t.Errorf("sameAttributes = %v, want %v", got, tt.want)
			}
		})
	}
}

// sameAttributes must not reorder the caller's slices; the stored content is
// sent to hooks as-is.
func TestSameAttributes_DoesNotMutate(t *testing.T) {
	a := map[string]interface{}{"v": []string{"b", "a"}}
	b := map[string]interface{}{"v": []string{"a", "b"}}
	sameAttributes(a, b)
	if got := a["v"].([]string); got[0] != "b" || got[1] != "a" {
		t.Errorf("sameAttributes reordered input: %v", got)
	}
}

func TestProcessHookResponse_UnchangedDerivedSearchKeepsRunning(t *testing.T) {
	resetState(t)

	stop := make(chan struct{})
	searchesMu.Lock()
	searches["42-posixGroups"] = &SearchSpec{
		Filter:  "(memberUid=42)",
		Refresh: 300,
		BaseDN:  "dc=unc,dc=edu",
		Stop:    stop,
	}
	searchesMu.Unlock()

	processHookResponse(HookResponse{Derived: []DerivedSearchSpec{{
		ID:      "42-posixGroups",
		Filter:  "(memberUid=42)",
		Refresh: 300,
		BaseDN:  "dc=unc,dc=edu",
	}}}, "src")

	select {
	case <-stop:
		t.Fatal("identical derived search was restarted")
	default:
	}

	searchesMu.RLock()
	got := searches["42-posixGroups"].Stop
	searchesMu.RUnlock()
	if got != stop {
		t.Error("identical derived search was replaced")
	}
}

func TestProcessHookResponse_ChangedDerivedSearchRestarts(t *testing.T) {
	resetState(t)

	stop := make(chan struct{})
	searchesMu.Lock()
	searches["42-posixGroups"] = &SearchSpec{
		Filter:  "(memberUid=42)",
		Refresh: 10,
		BaseDN:  "dc=unc,dc=edu",
		Stop:    stop,
	}
	searchesMu.Unlock()

	processHookResponse(HookResponse{Derived: []DerivedSearchSpec{{
		ID:      "42-posixGroups",
		Filter:  "(memberUid=42)",
		Refresh: 300,
		BaseDN:  "dc=unc,dc=edu",
	}}}, "src")

	select {
	case <-stop:
	default:
		t.Fatal("changed derived search was not restarted")
	}

	searchesMu.Lock()
	spec := searches["42-posixGroups"]
	close(spec.Stop)
	searchesMu.Unlock()
	if spec.Refresh != 300 {
		t.Errorf("refresh = %d, want 300", spec.Refresh)
	}
}
