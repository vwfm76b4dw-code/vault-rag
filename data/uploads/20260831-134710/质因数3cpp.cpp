#include <bits/stdc++.h>
using namespace std;
int a[10000];
int main()
{
	int n,i=2,t,cnt=0,max=0;
	cin>>n;
	t=n;
	while(i<=sqrt(t)){
		while(n%i==0){
			cout<<i<<" ";
			n/=i;
			if(i>max)max=i;
			a[i]++; 
		}
		i++;
	}
	if(n>sqrt(t)){
		cout<<n;
		if(n>max)max=n;
		a[n]++; 
	}
	cout<<endl;
	for(int i=2;i<=max;i++){
		if(a[i]!=0)cnt++;
	}
	cout<<cnt;
}
