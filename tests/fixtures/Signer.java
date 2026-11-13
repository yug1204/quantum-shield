package com.acme.sec;

import java.security.MessageDigest;
import java.security.KeyPairGenerator;
import java.util.List;
import java.util.Map;
import static java.lang.Math.max;

/** javadoc with { brace and foo() call */
@SuppressWarnings("unchecked")
public abstract class Signer<T> extends Object implements Runnable {
    private static final String ALGO = "RSA"; // comment {
    private int x = compute();
    char c = '{';
    String t = "}";

    static int compute() { return 1; }

    public Signer() { super(); init(); }

    void init() {}

    @Override
    public void run() {
        String s = "not a call: foo() { }";
        Runnable r = new Runnable() { public void run() { init(); } };
        try {
            KeyPairGenerator kpg = KeyPairGenerator.getInstance("RSA");
            kpg.initialize(2048);
            MessageDigest md = MessageDigest.getInstance("SHA-1");
        } catch (Exception e) { helper(1, null); }
        int m = max(1, 2);
        if (x > 0) { helper(x, null); }
        List<String> list = new java.util.ArrayList<>();
        list.forEach(v -> init());
    }

    private <K> Map<String, K> helper(final int a, List<String> b) throws IllegalStateException {
        return null;
    }

    abstract void todo();

    static class Inner { void go() { Signer.compute(); } }
}

interface Shape { double area(); }
