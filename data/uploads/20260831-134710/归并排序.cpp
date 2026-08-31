#include <bits/stdc++.h>
using namespace std;
int N;
int a[100005],t[100005];
void merge( int l, int m, int r) {
    int i = l;
    int j = m + 1;
    int k = l;
    while (i <= m && j <= r) {
        if (a[i] <= a[j])  t[k++] = a[i++];
        else    t[k++] = a[j++];
    }
    while (i <= m) t[k++] = a[i++];
    while (j <= r) t[k++] = a[j++];
    for (int i = l; i <= r; i++) {
        a[i] = t[i];
    }
}

void mergeSort(int l,int r){
	if(l >= r)return;
	int m = l + (r - l) / 2;
	mergeSort(l,m);
	mergeSort(m + 1,r);
	merge(l,m,r);
}
int main()
{
	cin >> N;
	for(int i = 1;i <= N;++ i)cin >> a[i];
	mergeSort(1,N);
	//sort(a + 1,a + N + 1);
	for(int i = 1;i <= N;++ i)cout << a[i] << " ";
	return 0;
}
