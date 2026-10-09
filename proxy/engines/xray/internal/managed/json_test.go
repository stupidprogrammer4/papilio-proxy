package managed

import "testing"

func TestJSONDuplicateDepthByteAndTrailingBoundaries(t *testing.T) {
	for _, payload := range []string{`{"a":{"x":1},"a":{"y":2}}`, `{"a":[{"x":1,"x":2}]}`, `{"a":1} {"b":2}`, `{"a":`, `{"a":[[[1]]]}`} {
		if CheckJSON([]byte(payload), 1024, 3) == nil {
			t.Fatalf("unsafe JSON accepted: %q", payload)
		}
	}
	if CheckJSON([]byte(`{"a":[1,{"b":2}]}`), 1024, 3) != nil {
		t.Fatal("bounded valid JSON rejected")
	}
	if CheckJSON([]byte(`{"a":1}`), 4, 3) == nil {
		t.Fatal("byte budget ignored")
	}
}
